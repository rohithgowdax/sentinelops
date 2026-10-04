"""
OpenTelemetry Span and Metric Exporters for SentinelOps.
"""
from __future__ import annotations

import json
from typing import Any

from sentinelops.observability.metrics import MetricsCollector
from sentinelops.observability.tracer import Span, Tracer


class OpenTelemetryJsonExporter:
    """Exports trace spans into W3C / OpenTelemetry standard JSON representations."""

    def __init__(self, tracer: Tracer, metrics: MetricsCollector | None = None) -> None:
        self.tracer = tracer
        self.metrics = metrics

    def export_spans_as_dict(self, trace_id: str | None = None) -> list[dict[str, Any]]:
        spans = self.tracer.get_spans(trace_id=trace_id)
        exported: list[dict[str, Any]] = []
        for s in spans:
            exported.append({
                "trace_id": s.trace_id,
                "span_id": s.span_id,
                "parent_span_id": s.parent_span_id,
                "name": s.name,
                "start_time": s.start_time.isoformat(),
                "end_time": s.end_time.isoformat() if s.end_time else None,
                "duration_seconds": s.duration_seconds,
                "status": {"code": s.status.value, "description": s.status_message},
                "attributes": s.attributes,
                "events": [{"name": ev.name, "timestamp": ev.timestamp.isoformat(), "attributes": ev.attributes} for ev in s.events],
            })
        return exported

    def export_spans_as_json(self, trace_id: str | None = None, indent: int = 2) -> str:
        return json.dumps(self.export_spans_as_dict(trace_id=trace_id), indent=indent)

    def export_metrics_as_dict(self) -> dict[str, Any]:
        if not self.metrics:
            return {}
        summaries = self.metrics.get_all_summaries()
        return {name: summ.model_dump() for name, summ in summaries.items()}
