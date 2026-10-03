"""
Unit tests for incident deduplication logic and domain events.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sentinelops.domain.models.incident import (
    EvidenceItem,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    TriggerType,
)
from sentinelops.domain.models.events import (
    IncidentCreatedEvent,
    TelemetryReceivedEvent,
)
from sentinelops.domain.models.telemetry import (
    MetricObservation,
    ResourceIdentity,
    SignalType,
    TelemetryRecord,
    TelemetrySource,
)


def _make_incident(
    episode_key: str = "rule-001::payments-service::production",
    status: IncidentStatus = IncidentStatus.OPEN,
) -> Incident:
    now = datetime.now(tz=timezone.utc)
    return Incident(
        created_at=now,
        updated_at=now,
        severity=IncidentSeverity.CRITICAL,
        status=status,
        service_name="payments-service",
        environment="production",
        trigger_type=TriggerType.METRIC_THRESHOLD,
        trigger_rule_id="rule-001",
        trigger_rule_name="Elevated Error Rate",
        title="[CRITICAL] Elevated Error Rate on payments-service",
        description="Error rate exceeded threshold.",
        source_provider="sentinelops-detector",
        source_integration_id="rule-001",
        episode_key=episode_key,
    )


class TestIncidentModel:
    def test_incident_id_auto_generated(self) -> None:
        inc = _make_incident()
        assert inc.incident_id.startswith("INC-")
        assert len(inc.incident_id) == 12  # "INC-" + 8 chars

    def test_episode_key_preserved(self) -> None:
        key = "rule-001::payments-service::production"
        inc = _make_incident(episode_key=key)
        assert inc.episode_key == key

    def test_status_default_open(self) -> None:
        inc = _make_incident()
        assert inc.status == IncidentStatus.OPEN

    def test_severity_enum(self) -> None:
        inc = _make_incident()
        assert inc.severity == IncidentSeverity.CRITICAL

    def test_evidence_list_default_empty(self) -> None:
        inc = _make_incident()
        assert inc.initial_evidence == []

    def test_incident_round_trips_json(self) -> None:
        inc = _make_incident()
        json_str = inc.model_dump_json()
        restored = Incident.model_validate_json(json_str)
        assert restored.incident_id == inc.incident_id
        assert restored.episode_key == inc.episode_key
        assert restored.severity == inc.severity


class TestIncidentCreatedEvent:
    def test_event_wraps_incident(self) -> None:
        inc = _make_incident()
        event = IncidentCreatedEvent(incident=inc)
        assert event.incident.incident_id == inc.incident_id
        assert event.event_type == "incident.created"

    def test_event_id_auto_generated(self) -> None:
        inc = _make_incident()
        e1 = IncidentCreatedEvent(incident=inc)
        e2 = IncidentCreatedEvent(incident=inc)
        assert e1.event_id != e2.event_id

    def test_event_round_trips_json(self) -> None:
        inc = _make_incident()
        event = IncidentCreatedEvent(incident=inc)
        json_str = event.model_dump_json()
        restored = IncidentCreatedEvent.model_validate_json(json_str)
        assert restored.incident.incident_id == inc.incident_id


class TestTelemetryReceivedEvent:
    def test_wraps_record(self) -> None:
        record = TelemetryRecord(
            timestamp=datetime.now(tz=timezone.utc),
            signal_type=SignalType.METRIC,
            source=TelemetrySource(provider="otel", integration_id="otel-001"),
            resource=ResourceIdentity(service_name="svc"),
            metric=MetricObservation(name="http.error_rate", value=0.18),
        )
        event = TelemetryReceivedEvent(telemetry=record)
        assert event.event_type == "telemetry.received"
        assert event.telemetry.metric is not None
        assert event.telemetry.metric.value == pytest.approx(0.18)

    def test_event_round_trips_json(self) -> None:
        record = TelemetryRecord(
            timestamp=datetime.now(tz=timezone.utc),
            signal_type=SignalType.METRIC,
            source=TelemetrySource(provider="otel", integration_id="otel-001"),
            resource=ResourceIdentity(service_name="svc"),
        )
        event = TelemetryReceivedEvent(telemetry=record)
        restored = TelemetryReceivedEvent.model_validate_json(event.model_dump_json())
        assert restored.telemetry.event_id == record.event_id
