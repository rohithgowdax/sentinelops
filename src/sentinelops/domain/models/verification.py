"""
Remediation Verification Domain Models for SentinelOps.

Defines:
- `RemediationStatus`: Overall recovery status (recovered, not_recovered, inconclusive).
- `MetricCheckResult`: Verification evaluation of an individual metric against baseline.
- `RemediationVerificationResult`: Comprehensive post-action verification evaluation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RemediationStatus(str, Enum):
    """Post-remediation operational recovery state."""

    RECOVERED = "recovered"
    NOT_RECOVERED = "not_recovered"
    INCONCLUSIVE = "inconclusive"


class MetricCheckResult(BaseModel):
    """Evaluation of an individual telemetry metric before vs after remediation."""

    metric_name: str
    before_value: float
    after_value: float
    threshold: float
    improved: bool
    healthy: bool
    detail: str


class RemediationVerificationResult(BaseModel):
    """
    Authoritative post-action verification result evaluating operational telemetry recovery.
    
    Invariants:
    - Based on observed post-action telemetry rather than provider return code.
    - Compares before/after telemetry across multiple signals.
    """

    incident_id: str
    action_id: str
    status: RemediationStatus = Field(..., description="Post-action recovery status")
    checks: list[MetricCheckResult] = Field(default_factory=list, description="Individual metric evaluations")
    before_metrics: dict[str, float] = Field(default_factory=dict, description="Pre-action degraded metric values")
    after_metrics: dict[str, float] = Field(default_factory=dict, description="Post-action observed metric values")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    explanation: str = Field(..., description="Technical explanation of recovery or lingering degradation")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @property
    def is_recovered(self) -> bool:
        return self.status == RemediationStatus.RECOVERED
