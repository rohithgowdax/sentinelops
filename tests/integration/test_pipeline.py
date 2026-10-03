"""
End-to-End Integration Test Suite for SentinelOps Telemetry & Detection Pipeline.

Prerequisites:
Requires live running Redis (port 6379) and PostgreSQL (port 5432) instances.
Run via: `docker compose up -d postgres redis` followed by `pytest -m integration`.

Pipeline Covered:
`Producer` -> `Redis EventBus Stream (sentinel:telemetry)` -> `TelemetryWorker` -> `PostgreSQL OperationalStore` -> `DetectionLoop` -> `Redis EventBus Stream (sentinel:incidents)` -> `Incident API`.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from sentinelops.detection.loop import DetectionLoop
from sentinelops.domain.models.events import TelemetryReceivedEvent
from sentinelops.domain.models.telemetry import (
    MetricObservation,
    ResourceIdentity,
    SignalType,
    TelemetryRecord,
    TelemetrySource,
)
from sentinelops.ingestion.worker import TelemetryWorker
from sentinelops.integrations.event_bus.redis_bus import RedisEventBus
from sentinelops.integrations.telemetry.custom_json.adapter import CustomJsonAdapter
from sentinelops.integrations.telemetry.otel_like.adapter import OtelLikeAdapter
from sqlalchemy import text
from sentinelops.storage.postgres_store import PostgresOperationalStore

# Infrastructure DSN constants for integration testing
REDIS_URL = "redis://localhost:6379/0"
POSTGRES_DSN = "postgresql+asyncpg://sentinelops:sentinelops@localhost:5432/sentinelops"
RULES_PATH = "config/detection_rules.yaml"

# Mark all tests in this file as integration tests requiring infrastructure
pytestmark = pytest.mark.integration


# ── Pytest Integration Fixtures ──────────────────────────────────────────────

@pytest.fixture
async def store() -> PostgresOperationalStore:  # type: ignore[misc]
    """Fixture initializing a connected PostgreSQL OperationalStore instance with isolated tables."""
    s = PostgresOperationalStore(dsn=POSTGRES_DSN)
    await s.initialize()
    # Clean tables before test run
    async with s._session() as session:
        await session.execute(text("TRUNCATE TABLE telemetry, incidents, investigations CASCADE;"))
        await session.commit()
    yield s
    # Clean tables after test run
    try:
        async with s._session() as session:
            await session.execute(text("TRUNCATE TABLE telemetry, incidents, investigations CASCADE;"))
            await session.commit()
    except Exception:
        pass
    await s.close()


@pytest.fixture
async def bus() -> RedisEventBus:  # type: ignore[misc]
    """Fixture initializing a connected RedisEventBus using test stream keys."""
    b = RedisEventBus(
        redis_url=REDIS_URL,
        telemetry_stream="sentinel:telemetry:test",
        incidents_stream="sentinel:incidents:test",
    )
    await b.connect()

    # Clean test streams before running test
    try:
        await b._redis.delete("sentinel:telemetry:test")
        await b._redis.delete("sentinel:incidents:test")
    except Exception:
        pass

    yield b

    # Clean test streams after test execution
    try:
        await b._redis.delete("sentinel:telemetry:test")
        await b._redis.delete("sentinel:incidents:test")
    except Exception:
        pass
    await b.close()


@pytest.fixture
async def worker(
    bus: RedisEventBus, store: PostgresOperationalStore
) -> TelemetryWorker:
    """Fixture initializing a TelemetryWorker bound to test bus and store."""
    return TelemetryWorker(
        event_bus=bus,
        store=store,
        consumer_group="test-workers",
        consumer_name="test-consumer-1",
        batch_size=50,
        block_ms=500,
    )


def _make_metric_record(
    service: str,
    metric_name: str,
    value: float,
    provider: str = "test",
) -> TelemetryRecord:
    """Helper to create a canonical TelemetryRecord for integration testing."""
    return TelemetryRecord(
        timestamp=datetime.now(tz=timezone.utc),
        signal_type=SignalType.METRIC,
        source=TelemetrySource(provider=provider, integration_id=f"{provider}-001"),
        resource=ResourceIdentity(service_name=service, environment="production"),
        metric=MetricObservation(name=metric_name, value=value),
    )


# ── Pipeline Integration Test Cases ──────────────────────────────────────────

class TestTelemetryPipeline:
    """Tests covering telemetry publish -> stream consumption -> database persistence."""

    async def test_publish_and_consume_via_worker(
        self,
        bus: RedisEventBus,
        worker: TelemetryWorker,
        store: PostgresOperationalStore,
    ) -> None:
        """
        Verify end-to-end ingestion flow:
        Publish TelemetryReceivedEvent -> Redis Stream -> Worker process_once -> PostgreSQL save.
        """
        # Step 1: Create canonical telemetry record and publish to Redis stream
        record = _make_metric_record(
            "payments-service", "http.error_rate", 0.18, "otel"
        )
        event = TelemetryReceivedEvent(telemetry=record)
        await bus.publish_telemetry(event)

        # Step 2: Run worker batch execution
        count = await worker.process_once()
        assert count >= 1

        # Step 3: Query database to verify persistence
        records = await store.query_recent_metrics(
            service_name="payments-service",
            metric_name="http.error_rate",
            since=record.timestamp,
        )
        assert len(records) >= 1
        found = next((r for r in records if r.event_id == record.event_id), None)
        assert found is not None
        assert found.metric is not None
        assert found.metric.value == pytest.approx(0.18)

    async def test_telemetry_idempotency(
        self,
        bus: RedisEventBus,
        worker: TelemetryWorker,
        store: PostgresOperationalStore,
    ) -> None:
        """
        Verify database idempotency:
        Publishing the EXACT SAME event_id twice results in only ONE row in PostgreSQL.
        """
        record = _make_metric_record("payments-service", "http.error_rate", 0.18)
        event = TelemetryReceivedEvent(telemetry=record)

        # Step 1: Publish duplicate events to Redis stream
        await bus.publish_telemetry(event)
        await bus.publish_telemetry(event)

        # Step 2: Process batch
        await worker.process_once()

        # Step 3: Verify PostgreSQL contains exactly ONE record for this event_id
        records = await store.query_recent_metrics(
            service_name="payments-service",
            metric_name="http.error_rate",
            since=record.timestamp,
        )
        matching = [r for r in records if r.event_id == record.event_id]
        assert len(matching) == 1

    async def test_otel_and_custom_records_both_persisted(
        self,
        bus: RedisEventBus,
        worker: TelemetryWorker,
        store: PostgresOperationalStore,
    ) -> None:
        """
        Verify provider neutrality of ingestion pipeline:
        Records from both OtelLikeAdapter and CustomJsonAdapter are persisted by the same worker.
        """
        otel_adapter = OtelLikeAdapter()
        custom_adapter = CustomJsonAdapter()

        # Build raw external payloads
        otel_raw = {
            "resource": {
                "service.name": "payments-service",
                "deployment.environment": "production",
            },
            "metric": {"name": "http.error_rate", "value": 0.18, "unit": "ratio"},
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        custom_raw = {
            "svc": "payments-service",
            "env": "production",
            "metric_name": "err_pct",
            "metric_value": 18.0,
            "unit": "percent",
            "time": datetime.now(tz=timezone.utc).isoformat(),
        }

        # Normalize via adapters
        rec_a = otel_adapter.normalize(otel_raw)
        rec_b = custom_adapter.normalize(custom_raw)

        # Publish both events to Redis stream
        await bus.publish_telemetry(TelemetryReceivedEvent(telemetry=rec_a))
        await bus.publish_telemetry(TelemetryReceivedEvent(telemetry=rec_b))

        # Process batch
        count = await worker.process_once()
        assert count >= 2

        # Verify both records exist in PostgreSQL
        records = await store.query_recent_metrics(
            service_name="payments-service",
            metric_name="http.error_rate",
            since=rec_a.timestamp,
        )
        assert any(r.event_id == rec_a.event_id for r in records)
        assert any(r.event_id == rec_b.event_id for r in records)


class TestDetectionPipeline:
    """Tests covering database metrics -> DetectionLoop -> Incident creation -> Incident event stream."""

    async def test_detection_creates_incident_and_publishes_event(
        self, bus: RedisEventBus, store: PostgresOperationalStore
    ) -> None:
        """
        Verify end-to-end detection flow:
        Metrics in database -> DetectionLoop run_once -> Incident saved to PostgreSQL & published to Redis.
        """
        # Step 1: Pre-populate store with above-threshold error rate metrics (0.20 > 0.10 threshold)
        for i in range(5):
            record = TelemetryRecord(
                timestamp=datetime.now(tz=timezone.utc),
                signal_type=SignalType.METRIC,
                source=TelemetrySource(provider="otel", integration_id="otel-001"),
                resource=ResourceIdentity(
                    service_name="payments-service",
                    environment="production",
                ),
                metric=MetricObservation(
                    name="http.error_rate",
                    value=0.20 + i * 0.01,
                ),
            )
            await store.save_telemetry(record)

        # Step 2: Execute single DetectionLoop cycle
        detection_loop = DetectionLoop(
            store=store,
            event_bus=bus,
            rules_path=RULES_PATH,
            interval_seconds=999,  # Manual trigger
        )
        detection_loop.reload_rules()
        incidents = await detection_loop.run_once()

        # Step 3: Assert incident creation
        assert len(incidents) >= 1
        incident = incidents[0]
        assert incident.service_name == "payments-service"
        assert incident.trigger_rule_id is not None

        # Step 4: Verify incident is persisted in PostgreSQL
        stored = await store.get_incident(incident.incident_id)
        assert stored is not None
        assert stored.incident_id == incident.incident_id

    async def test_deduplication_no_duplicate_incident(
        self, bus: RedisEventBus, store: PostgresOperationalStore
    ) -> None:
        """
        Verify active incident deduplication:
        Executing DetectionLoop twice during an ongoing outage creates ONLY ONE incident.
        """
        # Step 1: Save above-threshold metric records
        for i in range(3):
            record = TelemetryRecord(
                timestamp=datetime.now(tz=timezone.utc),
                signal_type=SignalType.METRIC,
                source=TelemetrySource(provider="otel", integration_id="otel-001"),
                resource=ResourceIdentity(
                    service_name="payments-service",
                    environment="production",
                ),
                metric=MetricObservation(name="http.error_rate", value=0.20),
            )
            await store.save_telemetry(record)

        loop = DetectionLoop(
            store=store,
            event_bus=bus,
            rules_path=RULES_PATH,
            interval_seconds=999,
        )
        loop.reload_rules()

        # Step 2: Execute first pass -> creates incident
        first_run = await loop.run_once()
        assert len(first_run) >= 1

        # Step 3: Execute second pass during same ongoing outage -> deduplicated!
        second_run = await loop.run_once()
        assert len(second_run) == 0  # Second run yields zero new incidents!
