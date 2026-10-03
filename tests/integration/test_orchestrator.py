"""
End-to-End Integration Tests for SentinelOps Orchestrator and Investigation API.

Verifies the complete Slice 2 pipeline:
1. Canonical Incident published to Redis stream (`sentinel:incidents`).
2. OrchestratorService consumes incident via `process_once()`.
3. LangGraph investigation executes (intake -> plan -> collect -> analyze -> diagnose -> verify -> finalize).
4. Investigation result is saved in PostgreSQL database (`investigations` table).
5. Incident message is acknowledged via `XACK` in Redis stream.
6. REST API `GET /incidents/{incident_id}/investigation` serves canonical investigation details.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from sentinelops.api.main import create_app
from sentinelops.domain.models.events import IncidentCreatedEvent
from sentinelops.domain.models.incident import (
    EvidenceItem,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    TriggerType,
)
from sentinelops.domain.models.investigation import (
    InvestigationResult,
    InvestigationStatus as InvStatus,
)
from sentinelops.domain.models.telemetry import (
    MetricObservation,
    ResourceIdentity,
    SignalType,
    TelemetryRecord,
    TelemetrySource,
)
from sentinelops.integrations.event_bus.redis_bus import RedisEventBus
from sentinelops.orchestrator.service import OrchestratorService
from sentinelops.storage.postgres_store import PostgresOperationalStore

REDIS_URL = "redis://localhost:6379/0"
POSTGRES_DSN = "postgresql+asyncpg://sentinelops:sentinelops@localhost:5432/sentinelops"

pytestmark = pytest.mark.integration


@pytest.fixture
async def store() -> PostgresOperationalStore:
    s = PostgresOperationalStore(dsn=POSTGRES_DSN)
    await s.initialize()
    async with s._session() as session:
        await session.execute(text("TRUNCATE TABLE telemetry, incidents, investigations CASCADE;"))
        await session.commit()
    yield s
    try:
        async with s._session() as session:
            await session.execute(text("TRUNCATE TABLE telemetry, incidents, investigations CASCADE;"))
            await session.commit()
    except Exception:
        pass
    await s.close()


@pytest.fixture
async def bus() -> RedisEventBus:
    b = RedisEventBus(
        redis_url=REDIS_URL,
        telemetry_stream="sentinel:telemetry:test",
        incidents_stream="sentinel:incidents:test",
    )
    await b.connect()
    try:
        await b._redis.delete("sentinel:telemetry:test")
        await b._redis.delete("sentinel:incidents:test")
    except Exception:
        pass
    yield b
    try:
        await b._redis.delete("sentinel:telemetry:test")
        await b._redis.delete("sentinel:incidents:test")
    except Exception:
        pass
    await b.close()


def _make_metric_record(service: str, metric_name: str, value: float) -> TelemetryRecord:
    return TelemetryRecord(
        timestamp=datetime.now(tz=timezone.utc),
        signal_type=SignalType.METRIC,
        source=TelemetrySource(provider="otel", integration_id="otel-test-1"),
        resource=ResourceIdentity(service_name=service, environment="production"),
        metric=MetricObservation(name=metric_name, value=value),
    )


class TestOrchestratorPipeline:
    """End-to-End Orchestrator and Investigation API integration tests."""

    @pytest.mark.asyncio
    async def test_full_investigation_pipeline_and_api(
        self,
        bus: RedisEventBus,
        store: PostgresOperationalStore,
    ) -> None:
        """
        Test entire lifecycle:
        1. Seed telemetry into PostgreSQL store.
        2. Publish canonical incident into Redis Stream.
        3. Orchestrator consumes incident, invokes LangGraph, saves InvestigationResult, and ACKs message.
        4. OperationalStore holds verified investigation record.
        5. API endpoint returns valid investigation.
        """
        service_name = "checkout-service"
        now = datetime.now(tz=timezone.utc)

        # Step 1: Seed telemetry into store
        for _ in range(5):
            rec = _make_metric_record(service_name, "http.error_rate", 0.24)
            await store.save_telemetry(rec)

        # Step 2: Create and save canonical Incident
        incident = Incident(
            incident_id="INC-INTEG-001",
            created_at=now,
            updated_at=now,
            severity=IncidentSeverity.CRITICAL,
            status=IncidentStatus.OPEN,
            service_name=service_name,
            service_namespace="core",
            environment="production",
            trigger_type=TriggerType.METRIC_THRESHOLD,
            trigger_rule_id="rule-checkout-error-spike",
            trigger_rule_name="Checkout Error Spike",
            title=f"Elevated error rate on {service_name}",
            description="HTTP error rate reached 0.24 (> 0.15 threshold)",
            source_provider="otel",
            source_integration_id="otel-test-1",
            episode_key=f"rule-checkout-error-spike::{service_name}::production",
            initial_evidence=[
                EvidenceItem(
                    kind="metric",
                    description="Observed error rate 0.24 > 0.15",
                    value=0.24,
                    attributes={"metric_name": "http.error_rate", "threshold": 0.15},
                )
            ],
        )
        await store.save_incident(incident)

        # Step 3: Publish IncidentCreatedEvent to Redis Stream
        event = IncidentCreatedEvent(incident=incident)
        await bus.publish_incident(event)

        # Step 4: Run Orchestrator service batch
        orchestrator = OrchestratorService(
            event_bus=bus,
            store=store,
            consumer_group="test-orchestrator-group",
            consumer_name="test-orchestrator-1",
            batch_size=10,
            block_ms=1000,
        )

        processed_count = await orchestrator.process_once()
        assert processed_count == 1

        # Step 5: Verify investigation persisted to PostgreSQL
        saved_investigation = await store.get_investigation("INC-INTEG-001")
        assert saved_investigation is not None
        assert saved_investigation.incident_id == "INC-INTEG-001"
        assert saved_investigation.status == InvStatus.DIAGNOSED
        assert saved_investigation.confidence >= 0.80
        assert saved_investigation.diagnosis is not None
        assert len(saved_investigation.diagnosis.supporting_evidence) > 0
        assert len(saved_investigation.supporting_evidence) > 0
        assert len(saved_investigation.investigation_steps) > 0

        # Step 6: Verify second process_once returns 0 (message was ACKed)
        second_pass = await orchestrator.process_once()
        assert second_pass == 0

        # Step 7: Test FastAPI REST API endpoint
        import sentinelops.api.main as api_module
        api_module._store = store

        app = create_app()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/incidents/INC-INTEG-001/investigation")
            assert resp.status_code == 200
            data = resp.json()
            assert data["incident_id"] == "INC-INTEG-001"
            assert data["status"] == "diagnosed"
            assert data["confidence"] >= 0.80
            assert "diagnosis" in data
            assert data["diagnosis"]["root_cause"] is not None

            # Non-existent incident returns 404
            resp_404 = await client.get("/incidents/INC-NONEXISTENT/investigation")
            assert resp_404.status_code == 404
