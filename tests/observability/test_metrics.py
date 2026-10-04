"""
Unit Tests for Lifecycle Metrics Collector and Statistical Aggregation.
"""
from __future__ import annotations

import pytest

from sentinelops.observability.metrics import MetricsCollector


class TestObservabilityMetrics:
    def test_metrics_duration_and_percentiles(self) -> None:
        collector = MetricsCollector()
        durations = [0.010, 0.020, 0.030, 0.040, 0.050, 0.060, 0.070, 0.080, 0.090, 0.100]
        for d in durations:
            collector.record_duration("time_to_diagnosis", d)

        summary = collector.get_summary("time_to_diagnosis")
        assert summary is not None
        assert summary.count == 10
        assert summary.mean == pytest.approx(0.055, abs=0.001)
        assert summary.p50 == pytest.approx(0.060, abs=0.005)
        assert summary.p95 == pytest.approx(0.100, abs=0.005)
        assert summary.min == 0.010
        assert summary.max == 0.100

    def test_counter_increments(self) -> None:
        collector = MetricsCollector()
        collector.increment("tool_calls_total", 1.0)
        collector.increment("tool_calls_total", 4.0)
        assert collector.get_counter("tool_calls_total") == 5.0

    def test_empty_metric_returns_none(self) -> None:
        collector = MetricsCollector()
        assert collector.get_summary("non_existent") is None
