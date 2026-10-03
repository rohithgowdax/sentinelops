"""
Unit tests for the detection engine — pure evaluation logic.

No I/O, no infrastructure dependencies.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from sentinelops.detection.engine import EvaluationResult, evaluate_rule, _aggregate, _compare
from sentinelops.detection.rules import Aggregation, DetectionRule, Operator
from sentinelops.domain.models.telemetry import (
    MetricObservation,
    ResourceIdentity,
    SignalType,
    TelemetryRecord,
    TelemetrySource,
)


def _make_rule(
    metric: str = "http.error_rate",
    operator: Operator = Operator.GT,
    threshold: float = 0.10,
    aggregation: Aggregation = Aggregation.LATEST,
    window_seconds: int = 60,
    severity: str = "critical",
) -> DetectionRule:
    return DetectionRule(
        rule_id="test-rule-001",
        name="Test Rule",
        signal="metric",
        metric=metric,
        operator=operator,
        threshold=threshold,
        window_seconds=window_seconds,
        severity=severity,
        service_filter="payments-service",
        aggregation=aggregation,
    )


def _make_record(value: float, metric_name: str = "http.error_rate") -> TelemetryRecord:
    return TelemetryRecord(
        timestamp=datetime.now(tz=timezone.utc),
        signal_type=SignalType.METRIC,
        source=TelemetrySource(provider="test", integration_id="t-001"),
        resource=ResourceIdentity(service_name="payments-service"),
        metric=MetricObservation(name=metric_name, value=value),
    )


class TestAggregation:
    def test_latest_returns_last(self) -> None:
        assert _aggregate([0.01, 0.05, 0.18], Aggregation.LATEST) == pytest.approx(0.18)

    def test_mean(self) -> None:
        assert _aggregate([0.10, 0.20, 0.30], Aggregation.MEAN) == pytest.approx(0.20)

    def test_max(self) -> None:
        assert _aggregate([0.05, 0.18, 0.12], Aggregation.MAX) == pytest.approx(0.18)

    def test_min(self) -> None:
        assert _aggregate([0.05, 0.18, 0.12], Aggregation.MIN) == pytest.approx(0.05)

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            _aggregate([], Aggregation.LATEST)


class TestCompare:
    def test_gt_fires(self) -> None:
        assert _compare(0.18, Operator.GT, 0.10) is True

    def test_gt_not_fires(self) -> None:
        assert _compare(0.05, Operator.GT, 0.10) is False

    def test_gte_fires_on_equal(self) -> None:
        assert _compare(0.10, Operator.GTE, 0.10) is True

    def test_lt_fires(self) -> None:
        assert _compare(0.05, Operator.LT, 0.10) is True

    def test_lte_fires_on_equal(self) -> None:
        assert _compare(0.10, Operator.LTE, 0.10) is True

    def test_eq_fires(self) -> None:
        assert _compare(0.10, Operator.EQ, 0.10) is True

    def test_eq_not_fires(self) -> None:
        assert _compare(0.11, Operator.EQ, 0.10) is False


class TestEvaluateRule:
    def test_fires_when_threshold_exceeded(self) -> None:
        rule = _make_rule(threshold=0.10, aggregation=Aggregation.LATEST)
        records = [_make_record(0.18)]
        result = evaluate_rule(rule, records, "payments-service", "production")
        assert result.fired is True
        assert result.observed_value == pytest.approx(0.18)

    def test_does_not_fire_below_threshold(self) -> None:
        rule = _make_rule(threshold=0.10)
        records = [_make_record(0.02)]
        result = evaluate_rule(rule, records, "payments-service", "production")
        assert result.fired is False

    def test_empty_records_no_fire(self) -> None:
        rule = _make_rule()
        result = evaluate_rule(rule, [], "payments-service", "production")
        assert result.fired is False
        assert result.observed_value is None
        assert result.sample_count == 0

    def test_records_for_wrong_metric_no_fire(self) -> None:
        """Records with a different metric name don't fire the rule."""
        rule = _make_rule(metric="http.error_rate")
        records = [_make_record(0.99, metric_name="cpu.usage")]
        result = evaluate_rule(rule, records, "payments-service", "production")
        assert result.fired is False

    def test_mean_aggregation_uses_mean(self) -> None:
        rule = _make_rule(threshold=0.10, aggregation=Aggregation.MEAN)
        # Mean of [0.05, 0.05, 0.18] = 0.093 < 0.10 → should not fire
        records = [
            _make_record(0.05),
            _make_record(0.05),
            _make_record(0.18),
        ]
        result = evaluate_rule(rule, records, "payments-service", "production")
        assert result.fired is False  # mean = 0.093

    def test_max_aggregation_fires(self) -> None:
        rule = _make_rule(threshold=0.10, aggregation=Aggregation.MAX)
        records = [_make_record(0.05), _make_record(0.05), _make_record(0.18)]
        result = evaluate_rule(rule, records, "payments-service", "production")
        assert result.fired is True  # max = 0.18

    def test_episode_key_stable(self) -> None:
        """The episode_key is deterministic for the same rule/service/env."""
        rule = _make_rule()
        records = [_make_record(0.18)]
        r1 = evaluate_rule(rule, records, "payments-service", "production")
        r2 = evaluate_rule(rule, records, "payments-service", "production")
        assert r1.episode_key == r2.episode_key

    def test_episode_key_differs_by_service(self) -> None:
        rule = _make_rule()
        records = [_make_record(0.18)]
        r1 = evaluate_rule(rule, records, "payments-service", None)
        r2 = evaluate_rule(rule, records, "other-service", None)
        assert r1.episode_key != r2.episode_key

    def test_sample_count_accurate(self) -> None:
        rule = _make_rule()
        records = [_make_record(0.18), _make_record(0.20), _make_record(0.15)]
        result = evaluate_rule(rule, records, "payments-service", None)
        assert result.sample_count == 3


class TestDetectionRuleValidation:
    def test_invalid_severity_raises(self) -> None:
        with pytest.raises(Exception):
            DetectionRule(
                rule_id="x",
                name="x",
                signal="metric",
                metric="m",
                operator="gt",
                threshold=0.1,
                window_seconds=60,
                severity="extreme",  # invalid
            )

    def test_negative_window_raises(self) -> None:
        with pytest.raises(Exception):
            DetectionRule(
                rule_id="x",
                name="x",
                signal="metric",
                metric="m",
                operator="gt",
                threshold=0.1,
                window_seconds=-10,
                severity="critical",
            )
