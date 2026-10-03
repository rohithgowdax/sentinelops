"""
Unit tests for PostgresTelemetryEvidenceProvider capability adapter.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from sentinelops.capabilities.evidence.telemetry_evidence import PostgresTelemetryEvidenceProvider
from sentinelops.domain.contracts.protocols import TelemetryEvidenceProvider
from sentinelops.domain.models.incident import (
    EvidenceItem,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    TriggerType,
)
from sentinelops.domain.models.telemetry import (
    MetricObservation,
    ResourceIdentity,
    SignalType,
    TelemetryRecord,
    TelemetrySource,
)


@pytest.fixture
def mock_store() -> AsyncMock:
    """Mock OperationalStore for capability tests."""
    return AsyncMock()


def _make_metric_record(
    service: str,
    metric_name: str,
    value: float,
    ts: datetime,
) -> TelemetryRecord:
    return TelemetryRecord(
        timestamp=ts,
        signal_type=SignalType.METRIC,
        source=TelemetrySource(provider="mock", integration_id="int-1"),
        resource=ResourceIdentity(service_name=service, environment="production"),
        metric=MetricObservation(name=metric_name, value=value, unit="ratio"),
    )


class TestPostgresTelemetryEvidenceProvider:
    """Test suite verifying TelemetryEvidenceProvider protocol implementation."""

    def test_satisfies_protocol(self, mock_store: AsyncMock) -> None:
        """Verify class satisfies TelemetryEvidenceProvider runtime checkable protocol."""
        provider = PostgresTelemetryEvidenceProvider(store=mock_store)
        assert isinstance(provider, TelemetryEvidenceProvider)

    @pytest.mark.asyncio
    async def test_query_recent_telemetry_computes_stats(self, mock_store: AsyncMock) -> None:
        """Verify query_recent_telemetry aggregates metrics accurately."""
        t1 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 1, 12, 1, 0, tzinfo=timezone.utc)
        t3 = datetime(2026, 10, 1, 12, 2, 0, tzinfo=timezone.utc)

        mock_store.query_recent_metrics.return_value = [
            _make_metric_record("order-service", "http.error_rate", 0.10, t1),
            _make_metric_record("order-service", "http.error_rate", 0.30, t2),
            _make_metric_record("order-service", "http.error_rate", 0.20, t3),
        ]

        provider = PostgresTelemetryEvidenceProvider(store=mock_store)
        res = await provider.query_recent_telemetry(
            service_name="order-service",
            metric_name="http.error_rate",
            lookback_seconds=900,
        )

        assert res["resource"] == "order-service"
        assert res["metric"] == "http.error_rate"
        assert res["sample_count"] == 3
        assert res["observed_min"] == 0.10
        assert res["observed_max"] == 0.30
        assert pytest.approx(res["observed_avg"]) == 0.20

    @pytest.mark.asyncio
    async def test_query_recent_telemetry_empty(self, mock_store: AsyncMock) -> None:
        """Verify behavior when no metrics are returned."""
        mock_store.query_recent_metrics.return_value = []
        provider = PostgresTelemetryEvidenceProvider(store=mock_store)
        res = await provider.query_recent_telemetry(
            service_name="order-service",
            metric_name="http.error_rate",
        )
        assert res["sample_count"] == 0
        assert res["observed_avg"] is None

    @pytest.mark.asyncio
    async def test_compare_telemetry_baseline(self, mock_store: AsyncMock) -> None:
        """Verify baseline ratio computation."""
        now = datetime.now(tz=timezone.utc)
        t_base = now - timedelta(seconds=1800)
        t_curr = now - timedelta(seconds=60)

        # Baseline: avg 0.02
        # Current: avg 0.20
        # Ratio: 10.0x
        mock_store.query_recent_metrics.return_value = [
            _make_metric_record("order-service", "http.error_rate", 0.02, t_base),
            _make_metric_record("order-service", "http.error_rate", 0.20, t_curr),
        ]

        provider = PostgresTelemetryEvidenceProvider(store=mock_store)
        res = await provider.compare_telemetry_baseline(
            service_name="order-service",
            metric_name="http.error_rate",
            baseline_window_seconds=7200,
            current_window_seconds=600,
        )

        assert res["resource"] == "order-service"
        assert res["baseline_avg"] == 0.02
        assert res["current_avg"] == 0.20
        assert res["elevation_ratio"] == 10.0
        assert res["is_elevated"] is True

    @pytest.mark.asyncio
    async def test_get_incident_trigger_context(self, mock_store: AsyncMock) -> None:
        """Verify initial evidence from incident is mapped to InvestigationEvidence."""
        now = datetime.now(tz=timezone.utc)
        incident = Incident(
            incident_id="INC-200",
            created_at=now,
            updated_at=now,
            service_name="payment-gateway",
            title="High Error Rate",
            description="Triggered by error threshold",
            severity=IncidentSeverity.CRITICAL,
            status=IncidentStatus.OPEN,
            trigger_type=TriggerType.METRIC_THRESHOLD,
            trigger_rule_id="rule-payment-errors",
            trigger_rule_name="Payment Error Rate Spike",
            source_provider="otel",
            source_integration_id="int-otel",
            episode_key="rule-payment-errors::payment-gateway::prod",
            initial_evidence=[
                EvidenceItem(
                    kind="metric",
                    description="Observed error rate 0.25 > threshold 0.15",
                    value=0.25,
                    attributes={"metric_name": "http.error_rate", "threshold": 0.15},
                )
            ],
        )

        provider = PostgresTelemetryEvidenceProvider(store=mock_store)
        res = await provider.get_incident_trigger_context(incident=incident)

        assert res["incident_id"] == "INC-200"
        assert res["trigger_rule_id"] == "rule-payment-errors"
        assert res["service_name"] == "payment-gateway"
        assert len(res["initial_evidence"]) == 1


