"""
Observability Module for SentinelOps (Slice 5 Observability).
"""
from sentinelops.observability.exporter import OpenTelemetryJsonExporter
from sentinelops.observability.metrics import MetricsCollector, get_metrics_collector
from sentinelops.observability.tracer import (
    Span,
    SpanStatus,
    Tracer,
    generate_span_id,
    generate_trace_id,
    get_tracer,
    sanitize_attributes,
)

__all__ = [
    "Tracer",
    "Span",
    "SpanStatus",
    "generate_trace_id",
    "generate_span_id",
    "sanitize_attributes",
    "get_tracer",
    "MetricsCollector",
    "get_metrics_collector",
    "OpenTelemetryJsonExporter",
]
