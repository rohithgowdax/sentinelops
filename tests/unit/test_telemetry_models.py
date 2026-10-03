"""
Unit tests for the canonical telemetry domain model (`TelemetryRecord`).

Verifies:
- Model instantiations and field validations.
- Automatic UUID event_id generation.
- Explicit event_id retention for idempotency.
- Raw payload retention.
- Pydantic JSON serialization and deserialization.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from sentinelops.domain.models.telemetry import (
    MetricObservation,
    ResourceIdentity,
    Severity,
    SignalType,
    TelemetryRecord,
    TelemetrySource,
)


class TestTelemetryRecord:
    """Test suite covering TelemetryRecord creation and behavior."""

    def test_valid_metric_record(self) -> None:
        """Verify that a well-formed TelemetryRecord with MetricObservation payload instantiates successfully."""
        record = TelemetryRecord(
            timestamp=datetime.now(tz=timezone.utc),
            signal_type=SignalType.METRIC,
            source=TelemetrySource(provider="test", integration_id="test-001"),
            resource=ResourceIdentity(service_name="payments-service"),
            metric=MetricObservation(name="http.error_rate", value=0.18, unit="ratio"),
        )
        assert record.event_id  # Automatically generated UUID string
        assert record.signal_type == SignalType.METRIC
        assert record.metric is not None
        assert record.metric.value == 0.18

    def test_event_id_is_unique(self) -> None:
        """Verify that distinct TelemetryRecord instances receive distinct auto-generated event_id values."""
        ts = datetime.now(tz=timezone.utc)
        source = TelemetrySource(provider="test", integration_id="t-001")
        resource = ResourceIdentity(service_name="svc")
        r1 = TelemetryRecord(
            timestamp=ts, signal_type=SignalType.METRIC, source=source, resource=resource
        )
        r2 = TelemetryRecord(
            timestamp=ts, signal_type=SignalType.METRIC, source=source, resource=resource
        )
        assert r1.event_id != r2.event_id

    def test_explicit_event_id_preserved(self) -> None:
        """Verify that providing an explicit event_id overrides automatic UUID generation."""
        eid = "my-stable-id-001"
        record = TelemetryRecord(
            event_id=eid,
            timestamp=datetime.now(tz=timezone.utc),
            signal_type=SignalType.LOG,
            source=TelemetrySource(provider="test", integration_id="t-001"),
            resource=ResourceIdentity(service_name="svc"),
        )
        assert record.event_id == eid

    def test_raw_payload_preserved(self) -> None:
        """Verify that raw_payload preserves the exact original untransformed external dictionary."""
        raw = {"svc": "payments", "err_pct": 18.4}
        record = TelemetryRecord(
            timestamp=datetime.now(tz=timezone.utc),
            signal_type=SignalType.METRIC,
            source=TelemetrySource(provider="custom_json", integration_id="c-001"),
            resource=ResourceIdentity(service_name="payments"),
            raw_payload=raw,
        )
        assert record.raw_payload == raw

    def test_metric_dimensions_default_empty(self) -> None:
        """Verify that metric dimensions default to an empty dictionary when omitted."""
        m = MetricObservation(name="cpu.usage", value=0.45)
        assert m.dimensions == {}

    def test_signal_type_enum_values(self) -> None:
        """Verify SignalType string values."""
        assert SignalType.METRIC.value == "metric"
        assert SignalType.LOG.value == "log"

    def test_serialise_deserialise(self) -> None:
        """Verify Pydantic JSON round-trip serialization (model_dump_json -> model_validate_json)."""
        record = TelemetryRecord(
            timestamp=datetime.now(tz=timezone.utc),
            signal_type=SignalType.METRIC,
            source=TelemetrySource(provider="otel", integration_id="otel-001"),
            resource=ResourceIdentity(service_name="checkout"),
            metric=MetricObservation(name="http.error_rate", value=0.05),
        )
        json_str = record.model_dump_json()
        restored = TelemetryRecord.model_validate_json(json_str)
        assert restored.event_id == record.event_id
        assert restored.metric is not None
        assert restored.metric.value == 0.05
