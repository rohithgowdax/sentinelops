"""
Operational & Lifecycle Metrics Collector for SentinelOps (Slice 5 Observability).

Tracks:
1. Operational Incident Lifecycle Timers:
   - time_to_detection
   - time_to_investigation_start
   - time_to_diagnosis
   - time_to_approval
   - time_to_execution
   - time_to_recovery
   - time_to_resolution
2. System & Component Latency Metrics:
   - agent_latency
   - tool_latency
   - retrieval_latency
   - mcp_latency
   - policy_latency
   - approval_wait_time
3. Reliability & Safety Counters:
   - error_rate
   - retry_rate
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class MetricPoint(BaseModel):
    name: str
    value: float
    unit: str = "seconds"
    labels: dict[str, str] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


class MetricSummary(BaseModel):
    name: str
    unit: str
    count: int
    mean: float
    p50: float
    p95: float
    min: float
    max: float


class MetricsCollector:
    """In-memory Prometheus / OpenTelemetry compatible metrics collector."""

    def __init__(self) -> None:
        self._values: dict[str, list[float]] = defaultdict(list)
        self._units: dict[str, str] = {}
        self._counters: dict[str, float] = defaultdict(float)

    def record_duration(
        self,
        metric_name: str,
        duration_seconds: float,
        unit: str = "seconds",
        labels: dict[str, str] | None = None,
    ) -> None:
        """Record a latency or lifecycle timer observation."""
        self._values[metric_name].append(max(0.0, float(duration_seconds)))
        self._units[metric_name] = unit

    def increment(
        self,
        counter_name: str,
        amount: float = 1.0,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Increment an operational counter."""
        self._counters[counter_name] += amount

    def get_summary(self, metric_name: str) -> MetricSummary | None:
        """Calculate statistical distribution for a metric."""
        vals = self._values.get(metric_name)
        if not vals:
            return None

        sorted_vals = sorted(vals)
        n = len(sorted_vals)
        p50_idx = int(n * 0.50)
        p95_idx = min(int(n * 0.95), n - 1)

        return MetricSummary(
            name=metric_name,
            unit=self._units.get(metric_name, "seconds"),
            count=n,
            mean=statistics.mean(sorted_vals),
            p50=sorted_vals[p50_idx],
            p95=sorted_vals[p95_idx],
            min=sorted_vals[0],
            max=sorted_vals[-1],
        )

    def get_all_summaries(self) -> dict[str, MetricSummary]:
        summaries: dict[str, MetricSummary] = {}
        for name in self._values:
            summ = self.get_summary(name)
            if summ:
                summaries[name] = summ
        return summaries

    def get_counter(self, counter_name: str) -> float:
        return self._counters.get(counter_name, 0.0)

    def clear(self) -> None:
        self._values.clear()
        self._units.clear()
        self._counters.clear()


# Global metrics instance
_default_metrics = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    return _default_metrics
