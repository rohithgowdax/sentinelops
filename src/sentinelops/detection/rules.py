"""
Detection Rule Schema and YAML Loader for SentinelOps.

Defines the structure of threshold detection rules configured via YAML (e.g. `config/detection_rules.yaml`).

Architectural Principle:
- Thresholds and rule parameters are NEVER hardcoded in Python code.
- Rules are loaded at runtime from YAML.
- Extensible design: New comparison operators or window aggregations can be added to Enums without refactoring the evaluation pipeline.
"""
from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import BaseModel, Field, field_validator

# Initialize logger
log = structlog.get_logger(__name__)


class SignalKind(str, Enum):
    """Supported signal category for detection rules (currently METRIC)."""

    METRIC = "metric"


class Operator(str, Enum):
    """
    Comparison operators supported by the Detection Engine.

    Attributes:
        GT: Greater than (observed > threshold).
        GTE: Greater than or equal (observed >= threshold).
        LT: Less than (observed < threshold).
        LTE: Less than or equal (observed <= threshold).
        EQ: Equal (observed == threshold).
    """

    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"


class Aggregation(str, Enum):
    """
    Aggregation strategies applied over telemetry time windows before comparison.

    Attributes:
        LATEST: Use the most recent telemetry data point in the look-back window.
        MEAN: Calculate arithmetic average across all points in the window.
        MAX: Use the peak/maximum value observed in the window.
        MIN: Use the minimum value observed in the window.
    """

    LATEST = "latest"
    MEAN = "mean"
    MAX = "max"
    MIN = "min"


class DetectionRule(BaseModel):
    """
    Pydantic schema representing a single threshold detection rule.

    Fields:
        rule_id: Unique string key identifying this rule (e.g. 'rule-001-elevated-errors').
        name: Human-readable title of the rule.
        signal: Signal category ('metric').
        metric: Canonical metric name evaluated by this rule (e.g. 'http.error_rate').
        operator: Operator enum ('gt', 'gte', 'lt', 'lte', 'eq').
        threshold: Numeric threshold value in canonical units (e.g. 0.10 for 10% ratio).
        window_seconds: Look-back time window duration in seconds.
        severity: Incident severity if fired ('low', 'medium', 'high', 'critical').
        service_filter: Optional service name to limit rule scope (e.g. 'payments-service').
        environment: Optional deployment environment filter (e.g. 'production').
        aggregation: Aggregation strategy across window samples (default: LATEST).
        enabled: Toggle boolean (default: True). Disabled rules are ignored at load.
        description: Informational explanation of why this rule exists.
    """

    rule_id: str = Field(description="Unique stable identifier for the rule.")
    name: str = Field(description="Human-readable rule title.")
    signal: SignalKind = Field(description="Signal category (METRIC).")
    metric: str = Field(description="Canonical metric name to evaluate.")
    operator: Operator = Field(description="Comparison operator enum.")
    threshold: float = Field(description="Numeric boundary threshold value.")
    window_seconds: int = Field(
        description="Look-back window duration in seconds."
    )
    severity: str = Field(
        description="Incident severity level ('low', 'medium', 'high', 'critical')."
    )
    service_filter: str | None = Field(
        default=None, description="Scope rule to a specific service name."
    )
    environment: str | None = Field(
        default=None, description="Scope rule to a target environment."
    )
    aggregation: Aggregation = Field(
        default=Aggregation.LATEST,
        description="Window aggregation strategy (LATEST, MEAN, MAX, MIN).",
    )
    enabled: bool = Field(
        default=True, description="Whether this rule is active."
    )
    description: str = Field(
        default="", description="Detailed description of rule purpose."
    )

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        """Validator enforcing severity values match IncidentSeverity strings."""
        valid = {"low", "medium", "high", "critical"}
        if v.lower() not in valid:
            raise ValueError(f"severity must be one of {valid}, got '{v}'")
        return v.lower()

    @field_validator("window_seconds")
    @classmethod
    def validate_window(cls, v: int) -> int:
        """Validator enforcing look-back windows are strictly positive integer seconds."""
        if v <= 0:
            raise ValueError("window_seconds must be a positive integer > 0")
        return v


def load_rules(path: str | Path) -> list[DetectionRule]:
    """
    Parse and validate YAML detection rules file.

    Features:
    - Safe parsing using PyYAML.
    - Gracefully skips individual malformed rules while logging a warning.
    - Filters out disabled rules (`enabled: false`).

    Args:
        path: File system path to `detection_rules.yaml`.

    Returns:
        List of validated and active `DetectionRule` objects.
    """
    path = Path(path)
    # Check if rule configuration file exists
    if not path.exists():
        log.warning("detection_rules.file_not_found", path=str(path))
        return []

    # Read YAML contents
    with path.open() as f:
        raw = yaml.safe_load(f)

    # Validate top-level schema structure
    if not isinstance(raw, dict) or "rules" not in raw:
        raise ValueError(
            f"Detection rules file must have a top-level 'rules' key. Got keys: {list(raw.keys()) if isinstance(raw, dict) else type(raw)}"
        )

    rules: list[DetectionRule] = []
    # Parse each rule entry
    for i, item in enumerate(raw["rules"]):
        try:
            rule = DetectionRule.model_validate(item)
            # Only include enabled rules
            if rule.enabled:
                rules.append(rule)
                log.debug(
                    "detection_rule.loaded", rule_id=rule.rule_id, name=rule.name
                )
        except Exception as exc:
            # Log invalid rule entries without crashing the load process
            log.warning("detection_rule.invalid", index=i, error=str(exc), item=item)

    log.info("detection_rules.loaded", count=len(rules), path=str(path))
    return rules
