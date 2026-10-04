"""
Unit Tests for OpenTelemetryJsonExporter.
"""
from __future__ import annotations

import json
import pytest

from sentinelops.observability.exporter import OpenTelemetryJsonExporter
from sentinelops.observability.metrics import MetricsCollector
from sentinelops.observability.tracer import Tracer


class TestObservabilityExporter:
    def test_json_span_export(self) -> None:
        tracer = Tracer(service_name="payments-service")
        metrics = MetricsCollector()
        with tracer.span("investigation.diagnose", attributes={"incident_id": "INC-123"}) as span:
            span.set_attribute("gen_ai.request.model", "deterministic-rules")

        metrics.record_duration("agent_latency", 0.045)
        exporter = OpenTelemetryJsonExporter(tracer=tracer, metrics=metrics)

        spans_json = exporter.export_spans_as_json()
        parsed = json.loads(spans_json)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "investigation.diagnose"
        assert parsed[0]["attributes"]["incident_id"] == "INC-123"
        assert parsed[0]["attributes"]["service.name"] == "payments-service"

        metrics_dict = exporter.export_metrics_as_dict()
        assert "agent_latency" in metrics_dict
        assert metrics_dict["agent_latency"]["count"] == 1
