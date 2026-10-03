"""Detection package."""
from sentinelops.detection.rules import DetectionRule, load_rules, Operator, Aggregation
from sentinelops.detection.engine import evaluate_rule, EvaluationResult
from sentinelops.detection.loop import DetectionLoop

__all__ = [
    "DetectionRule",
    "load_rules",
    "Operator",
    "Aggregation",
    "evaluate_rule",
    "EvaluationResult",
    "DetectionLoop",
]
