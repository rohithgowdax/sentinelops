"""
Detection Engine — Pure Deterministic Rule Evaluator for SentinelOps.

Architectural Invariants:
1. PURE FUNCTIONALITY: `evaluate_rule` performs NO I/O (no database or network calls).
2. DETERMINISM: Returns identical `EvaluationResult` given the same rule and telemetry records.
3. PROVIDER NEUTRALITY: Evaluates canonical `TelemetryRecord` objects without inspecting `source.provider`.

Evaluation Lifecycle:
1. Filters input `TelemetryRecord` list for canonical `metric.name == rule.metric`.
2. Applies window aggregation strategy (LATEST, MEAN, MAX, MIN).
3. Compares aggregated value against numeric `rule.threshold` using `rule.operator` (gt, gte, lt, lte, eq).
4. Produces immutable `EvaluationResult` dataclass containing `episode_key` for deduplication.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from sentinelops.detection.rules import Aggregation, DetectionRule, Operator
from sentinelops.domain.models.telemetry import TelemetryRecord

# Initialize logger
log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EvaluationResult:
    """
    Immutable result container produced by evaluating a single detection rule.

    Fields:
        rule: The `DetectionRule` instance evaluated.
        fired: Boolean indicating whether the threshold condition was met.
        observed_value: Aggregated numerical metric value observed (or None if no samples).
        sample_count: Number of telemetry samples found in the look-back window.
        evaluated_at: UTC timestamp when evaluation occurred.
        service_name: Name of the service evaluated.
        environment: Deployment environment evaluated.
    """

    rule: DetectionRule
    fired: bool
    observed_value: float | None
    sample_count: int
    evaluated_at: datetime
    service_name: str
    environment: str | None = None

    @property
    def episode_key(self) -> str:
        """
        Calculates the stable composite key used to track active incident episodes.

        Format: `"{rule_id}::{service_name}::{environment}"` (e.g. 'rule-001::payments-service::production').

        Used by `DetectionLoop` to query `OperationalStore` and prevent duplicate incident creation.
        """
        env_part = self.environment or "any"
        return f"{self.rule.rule_id}::{self.service_name}::{env_part}"


def _aggregate(values: list[float], strategy: Aggregation) -> float:
    """
    Private helper: Reduces a non-empty list of metric values into a single value using the configured strategy.

    Assumes input `values` list is ordered by timestamp ASCENDING.

    Args:
        values: List of float metric observations.
        strategy: Aggregation strategy enum (LATEST, MEAN, MAX, MIN).

    Returns:
        Single aggregated floating-point value.

    Raises:
        ValueError: If `values` is empty or strategy is unknown.
    """
    if not values:
        raise ValueError("Cannot aggregate empty list of values.")

    if strategy == Aggregation.LATEST:
        # Array is ordered timestamp ASC -> last element is newest
        return values[-1]
    if strategy == Aggregation.MEAN:
        return statistics.mean(values)
    if strategy == Aggregation.MAX:
        return max(values)
    if strategy == Aggregation.MIN:
        return min(values)

    raise ValueError(f"Unknown aggregation strategy: {strategy}")


def _compare(observed: float, operator: Operator, threshold: float) -> bool:
    """
    Private helper: Compares an observed numeric value against a threshold.

    Evaluates: `observed <operator> threshold` (e.g., `0.18 > 0.10`).

    Args:
        observed: Aggregated value calculated from metric samples.
        operator: Comparison operator enum (GT, GTE, LT, LTE, EQ).
        threshold: Rule boundary threshold value.

    Returns:
        Boolean result of the comparison operator.

    Raises:
        ValueError: If operator is unknown.
    """
    ops = {
        Operator.GT: lambda a, b: a > b,
        Operator.GTE: lambda a, b: a >= b,
        Operator.LT: lambda a, b: a < b,
        Operator.LTE: lambda a, b: a <= b,
        Operator.EQ: lambda a, b: a == b,
    }
    fn = ops.get(operator)
    if fn is None:
        raise ValueError(f"Unknown comparison operator: {operator}")
    return fn(observed, threshold)


def evaluate_rule(
    rule: DetectionRule,
    records: list[TelemetryRecord],
    service_name: str,
    environment: str | None,
) -> EvaluationResult:
    """
    Pure function that evaluates a single detection rule against pre-fetched canonical telemetry records.

    This function executes zero database queries, network calls, or side effects.

    Workflow:
    1. Filter `records` for items matching `rec.metric.name == rule.metric`.
    2. Extract numeric values into `values: list[float]`.
    3. Aggregate values via `_aggregate(values, rule.aggregation)`.
    4. Evaluate operator comparison via `_compare(observed, rule.operator, rule.threshold)`.
    5. Construct and return `EvaluationResult`.

    Args:
        rule: `DetectionRule` configuration model.
        records: List of `TelemetryRecord` items sorted by timestamp ASC.
        service_name: Name of the service being evaluated.
        environment: Target environment string.

    Returns:
        `EvaluationResult` detailing whether the rule fired.
    """
    now = datetime.now(tz=timezone.utc)

    # Short-circuit if no telemetry records were fetched
    if not records:
        return EvaluationResult(
            rule=rule,
            fired=False,
            observed_value=None,
            sample_count=0,
            evaluated_at=now,
            service_name=service_name,
            environment=environment,
        )

    # Step 1: Extract numeric metric values matching rule.metric (Provider Neutral check)
    values: list[float] = []
    for rec in records:
        if rec.metric and rec.metric.name == rule.metric:
            values.append(rec.metric.value)

    # Short-circuit if no matching metric observations were found
    if not values:
        return EvaluationResult(
            rule=rule,
            fired=False,
            observed_value=None,
            sample_count=0,
            evaluated_at=now,
            service_name=service_name,
            environment=environment,
        )

    # Step 2: Aggregate window samples
    try:
        observed = _aggregate(values, rule.aggregation)
    except ValueError as exc:
        log.error("detection.aggregation_error", rule_id=rule.rule_id, error=str(exc))
        return EvaluationResult(
            rule=rule,
            fired=False,
            observed_value=None,
            sample_count=len(values),
            evaluated_at=now,
            service_name=service_name,
            environment=environment,
        )

    # Step 3: Compare aggregated value against rule threshold
    fired = _compare(observed, rule.operator, rule.threshold)

    log.debug(
        "detection.rule_evaluated",
        rule_id=rule.rule_id,
        service=service_name,
        observed=observed,
        threshold=rule.threshold,
        operator=rule.operator.value,
        fired=fired,
        samples=len(values),
    )

    # Step 4: Return immutable EvaluationResult
    return EvaluationResult(
        rule=rule,
        fired=fired,
        observed_value=observed,
        sample_count=len(values),
        evaluated_at=now,
        service_name=service_name,
        environment=environment,
    )
