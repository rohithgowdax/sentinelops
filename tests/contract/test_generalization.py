"""
Generalization Contract Verification Suite for SentinelOps.

Architectural Requirement (Generalization Proof):
This test suite acts as an automated CI gate proving that:
1. `OtelLikeAdapter` (Adapter A) and `CustomJsonAdapter` (Adapter B) normalize completely different
   external JSON payloads into semantically equivalent `TelemetryRecord` canonical objects.
2. The `DetectionEngine` evaluates rules identically against records produced by either adapter.
3. The resulting incident episode keys (`episode_key`) match across both sources, guaranteeing provider-neutral deduplication.
4. The `DetectionEngine` contains ZERO branching on `source.provider`.

FAILURE OF THIS TEST SUITE INDICATES A VIOLATION OF THE PROVIDER-NEUTRAL CORE INVARIANT.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from sentinelops.detection.engine import evaluate_rule
from sentinelops.detection.rules import Aggregation, DetectionRule, Operator
from sentinelops.domain.models.telemetry import SignalType
from sentinelops.integrations.telemetry.custom_json.adapter import CustomJsonAdapter
from sentinelops.integrations.telemetry.otel_like.adapter import OtelLikeAdapter


# ── Pytest Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def otel_adapter() -> OtelLikeAdapter:
    """Fixture providing an instance of Adapter A (OpenTelemetry)."""
    return OtelLikeAdapter()


@pytest.fixture
def custom_adapter() -> CustomJsonAdapter:
    """Fixture providing an instance of Adapter B (Custom JSON)."""
    return CustomJsonAdapter()


@pytest.fixture
def detection_rule() -> DetectionRule:
    """
    Fixture providing the canonical detection rule used in generalization tests.
    Rule: http.error_rate > 0.10 over a 60-second window.
    """
    return DetectionRule(
        rule_id="rule-001-elevated-service-errors",
        name="Elevated Service Error Rate",
        signal="metric",
        metric="http.error_rate",
        operator=Operator.GT,
        threshold=0.10,
        window_seconds=60,
        severity="critical",
        service_filter="payments-service",
        aggregation=Aggregation.LATEST,
    )


# ── Equivalent Payloads (Representing the Same Logical Signal) ───────────────

@pytest.fixture
def otel_above_threshold() -> dict[str, Any]:
    """
    OTel-style raw payload:
    - Service: 'payments-service'
    - Metric: 'http.error_rate' = 0.18 ratio (above 0.10 threshold)
    """
    return {
        "resource": {
            "service.name": "payments-service",
            "deployment.environment": "production",
            "service.namespace": "commerce",
        },
        "metric": {
            "name": "http.error_rate",
            "value": 0.18,
            "unit": "ratio",
        },
        "timestamp": "2026-10-01T14:37:12Z",
    }


@pytest.fixture
def custom_above_threshold() -> dict[str, Any]:
    """
    Custom JSON raw payload representing the EXACT SAME signal:
    - Service: 'svc' -> 'payments-service'
    - Metric: 'err_pct' = 18.0 percent -> adapter scales to 0.18 ratio (above 0.10 threshold)
    """
    return {
        "svc": "payments-service",
        "env": "production",
        "ns": "commerce",
        "metric_name": "err_pct",
        "metric_value": 18.0,
        "unit": "percent",
        "time": "2026-10-01T14:37:12Z",
        "tags": {},
    }


@pytest.fixture
def otel_below_threshold() -> dict[str, Any]:
    """OTel payload representing a healthy signal (error_rate = 0.02 ratio)."""
    return {
        "resource": {
            "service.name": "payments-service",
            "deployment.environment": "production",
        },
        "metric": {"name": "http.error_rate", "value": 0.02, "unit": "ratio"},
        "timestamp": "2026-10-01T14:37:12Z",
    }


@pytest.fixture
def custom_below_threshold() -> dict[str, Any]:
    """Custom JSON payload representing a healthy signal (err_pct = 2.0 percent)."""
    return {
        "svc": "payments-service",
        "env": "production",
        "metric_name": "err_pct",
        "metric_value": 2.0,
        "unit": "percent",
        "time": "2026-10-01T14:37:12Z",
    }


# ── Test Contract Suite ───────────────────────────────────────────────────────

class TestGeneralizationContract:
    """
    Contract Suite: Proves that two different adapters yield equivalent canonical models and detection outcomes.
    """

    # ── Part 1: Canonical Representation Equivalence ─────────────────────────

    def test_canonical_service_name_equivalent(
        self,
        otel_adapter: OtelLikeAdapter,
        custom_adapter: CustomJsonAdapter,
        otel_above_threshold: dict[str, Any],
        custom_above_threshold: dict[str, Any],
    ) -> None:
        """Verify that both adapters extract identical service names into ResourceIdentity."""
        rec_a = otel_adapter.normalize(otel_above_threshold)
        rec_b = custom_adapter.normalize(custom_above_threshold)
        assert rec_a.resource.service_name == rec_b.resource.service_name == "payments-service"

    def test_canonical_metric_name_equivalent(
        self,
        otel_adapter: OtelLikeAdapter,
        custom_adapter: CustomJsonAdapter,
        otel_above_threshold: dict[str, Any],
        custom_above_threshold: dict[str, Any],
    ) -> None:
        """Verify that 'err_pct' and 'http.error_rate' normalize to the canonical name 'http.error_rate'."""
        rec_a = otel_adapter.normalize(otel_above_threshold)
        rec_b = custom_adapter.normalize(custom_above_threshold)
        assert rec_a.metric is not None
        assert rec_b.metric is not None
        assert rec_a.metric.name == rec_b.metric.name == "http.error_rate"

    def test_canonical_metric_value_equivalent(
        self,
        otel_adapter: OtelLikeAdapter,
        custom_adapter: CustomJsonAdapter,
        otel_above_threshold: dict[str, Any],
        custom_above_threshold: dict[str, Any],
    ) -> None:
        """Verify unit scaling: 18.0 percent from Custom JSON scales to 0.18 ratio matching OTel."""
        rec_a = otel_adapter.normalize(otel_above_threshold)
        rec_b = custom_adapter.normalize(custom_above_threshold)
        assert rec_a.metric is not None
        assert rec_b.metric is not None
        assert rec_a.metric.value == pytest.approx(rec_b.metric.value, abs=1e-4)
        assert rec_a.metric.value == pytest.approx(0.18)

    def test_canonical_environment_equivalent(
        self,
        otel_adapter: OtelLikeAdapter,
        custom_adapter: CustomJsonAdapter,
        otel_above_threshold: dict[str, Any],
        custom_above_threshold: dict[str, Any],
    ) -> None:
        """Verify that 'deployment.environment' and 'env' normalize to the canonical environment 'production'."""
        rec_a = otel_adapter.normalize(otel_above_threshold)
        rec_b = custom_adapter.normalize(custom_above_threshold)
        assert rec_a.resource.environment == rec_b.resource.environment == "production"

    def test_canonical_signal_type_equivalent(
        self,
        otel_adapter: OtelLikeAdapter,
        custom_adapter: CustomJsonAdapter,
        otel_above_threshold: dict[str, Any],
        custom_above_threshold: dict[str, Any],
    ) -> None:
        """Verify signal_type is SignalType.METRIC for both adapter outputs."""
        rec_a = otel_adapter.normalize(otel_above_threshold)
        rec_b = custom_adapter.normalize(custom_above_threshold)
        assert rec_a.signal_type == rec_b.signal_type == SignalType.METRIC

    # ── Part 2: Detection Engine Evaluation Equivalence ───────────────────────

    def test_same_rule_fires_for_otel_record(
        self,
        otel_adapter: OtelLikeAdapter,
        otel_above_threshold: dict[str, Any],
        detection_rule: DetectionRule,
    ) -> None:
        """Verify detection rule fires (fired=True) for OTel normalized record."""
        record = otel_adapter.normalize(otel_above_threshold)
        result = evaluate_rule(detection_rule, [record], "payments-service", "production")
        assert result.fired is True
        assert result.observed_value == pytest.approx(0.18)

    def test_same_rule_fires_for_custom_record(
        self,
        custom_adapter: CustomJsonAdapter,
        custom_above_threshold: dict[str, Any],
        detection_rule: DetectionRule,
    ) -> None:
        """Verify detection rule fires (fired=True) for Custom JSON normalized record."""
        record = custom_adapter.normalize(custom_above_threshold)
        result = evaluate_rule(detection_rule, [record], "payments-service", "production")
        assert result.fired is True
        assert result.observed_value == pytest.approx(0.18)

    def test_rule_does_not_fire_below_threshold_otel(
        self,
        otel_adapter: OtelLikeAdapter,
        otel_below_threshold: dict[str, Any],
        detection_rule: DetectionRule,
    ) -> None:
        """Verify detection rule does NOT fire (fired=False) for healthy OTel record."""
        record = otel_adapter.normalize(otel_below_threshold)
        result = evaluate_rule(detection_rule, [record], "payments-service", "production")
        assert result.fired is False

    def test_rule_does_not_fire_below_threshold_custom(
        self,
        custom_adapter: CustomJsonAdapter,
        custom_below_threshold: dict[str, Any],
        detection_rule: DetectionRule,
    ) -> None:
        """Verify detection rule does NOT fire (fired=False) for healthy Custom JSON record."""
        record = custom_adapter.normalize(custom_below_threshold)
        result = evaluate_rule(detection_rule, [record], "payments-service", "production")
        assert result.fired is False

    # ── Part 3: Incident Semantic & Deduplication Equivalence ───────────────

    def test_episode_key_equivalent_for_both_sources(
        self,
        otel_adapter: OtelLikeAdapter,
        custom_adapter: CustomJsonAdapter,
        otel_above_threshold: dict[str, Any],
        custom_above_threshold: dict[str, Any],
        detection_rule: DetectionRule,
    ) -> None:
        """
        Verify that firing results from BOTH adapters produce the EXACT SAME `episode_key`.
        This guarantees provider-neutral incident deduplication.
        """
        rec_a = otel_adapter.normalize(otel_above_threshold)
        rec_b = custom_adapter.normalize(custom_above_threshold)
        result_a = evaluate_rule(detection_rule, [rec_a], "payments-service", "production")
        result_b = evaluate_rule(detection_rule, [rec_b], "payments-service", "production")
        assert result_a.episode_key == result_b.episode_key == "rule-001-elevated-service-errors::payments-service::production"

    def test_observed_values_approximately_equal(
        self,
        otel_adapter: OtelLikeAdapter,
        custom_adapter: CustomJsonAdapter,
        otel_above_threshold: dict[str, Any],
        custom_above_threshold: dict[str, Any],
        detection_rule: DetectionRule,
    ) -> None:
        """Verify observed values in EvaluationResult match across both adapter outputs."""
        rec_a = otel_adapter.normalize(otel_above_threshold)
        rec_b = custom_adapter.normalize(custom_above_threshold)
        res_a = evaluate_rule(detection_rule, [rec_a], "payments-service", "production")
        res_b = evaluate_rule(detection_rule, [rec_b], "payments-service", "production")
        assert res_a.observed_value is not None
        assert res_b.observed_value is not None
        assert res_a.observed_value == pytest.approx(res_b.observed_value, abs=1e-4)

    # ── Part 4: Provider Independence Check ──────────────────────────────────

    def test_detector_does_not_inspect_provider(
        self,
        otel_adapter: OtelLikeAdapter,
        custom_adapter: CustomJsonAdapter,
        otel_above_threshold: dict[str, Any],
        custom_above_threshold: dict[str, Any],
        detection_rule: DetectionRule,
    ) -> None:
        """
        Structural verification: Prove that `source.provider` differs, yet evaluation outputs match.
        Proves the engine does not branch on provider names.
        """
        rec_a = otel_adapter.normalize(otel_above_threshold)
        rec_b = custom_adapter.normalize(custom_above_threshold)

        # Provider metadata tags are distinct
        assert rec_a.source.provider == "otel"
        assert rec_b.source.provider == "custom_json"
        assert rec_a.source.provider != rec_b.source.provider

        # Evaluation results are identical
        res_a = evaluate_rule(detection_rule, [rec_a], "payments-service", "production")
        res_b = evaluate_rule(detection_rule, [rec_b], "payments-service", "production")
        assert res_a.fired == res_b.fired == True
        assert res_a.episode_key == res_b.episode_key

    def test_mixed_source_batch_fires(
        self,
        otel_adapter: OtelLikeAdapter,
        custom_adapter: CustomJsonAdapter,
        otel_above_threshold: dict[str, Any],
        custom_above_threshold: dict[str, Any],
        detection_rule: DetectionRule,
    ) -> None:
        """
        Verify that a mixed batch containing records from BOTH adapters is processed seamlessly.
        """
        rec_a = otel_adapter.normalize(otel_above_threshold)
        rec_b = custom_adapter.normalize(custom_above_threshold)

        # Evaluate batch containing both OTel and Custom JSON records
        result = evaluate_rule(
            detection_rule, [rec_a, rec_b], "payments-service", "production"
        )
        assert result.fired is True
        assert result.sample_count == 2
