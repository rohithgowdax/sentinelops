"""
Policy and Authorization Domain Models for SentinelOps.

Defines:
- `ActorRole`: Typed operator roles (operator, sre, incident_commander, admin).
- `ActorContext`: Authenticated actor identity and role.
- `PolicyDecisionType`: Deterministic policy outcomes (ALLOW, REQUIRES_APPROVAL, DENY).
- `PolicyDecision`: Authoritative decision returned by PolicyEngine.
- `PolicyRule`: Declarative policy rule representation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from sentinelops.domain.models.action import ActionType, RiskClass


class ActorRole(str, Enum):
    """Typed roles in operational hierarchy."""

    OPERATOR = "operator"
    SRE = "sre"
    INCIDENT_COMMANDER = "incident_commander"
    ADMIN = "admin"


# Role hierarchy definition (higher roles inherit lower permissions)
ROLE_HIERARCHY: dict[ActorRole, int] = {
    ActorRole.OPERATOR: 1,
    ActorRole.SRE: 2,
    ActorRole.INCIDENT_COMMANDER: 3,
    ActorRole.ADMIN: 4,
}


class ActorContext(BaseModel):
    """Authenticated human operator identity for approval / authorization context."""

    actor_id: str = Field(..., description="Unique user or service account identifier")
    role: ActorRole = Field(..., description="Assigned authorization role")
    name: str = Field(default="", description="Human-readable actor name")
    email: str | None = Field(default=None)

    def has_sufficient_role(self, required_role: ActorRole) -> bool:
        """Check if actor role meets or exceeds required authorization tier."""
        return ROLE_HIERARCHY.get(self.role, 0) >= ROLE_HIERARCHY.get(required_role, 99)


class PolicyDecisionType(str, Enum):
    """Deterministic policy outcomes."""

    ALLOW = "allow"
    REQUIRES_APPROVAL = "requires_approval"
    DENY = "deny"


class PolicyDecision(BaseModel):
    """Authoritative decision returned by PolicyEngine for an ActionRequest."""

    decision: PolicyDecisionType = Field(..., description="Evaluation outcome")
    reason: str = Field(..., description="Deterministic justification for policy decision")
    required_role: ActorRole | None = Field(default=None, description="Minimum role required if approval needed")
    risk_class: RiskClass = Field(..., description="Assessed risk classification")
    rule_id: str | None = Field(default=None, description="Identifier of matching policy rule")
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @property
    def is_allowed(self) -> bool:
        return self.decision == PolicyDecisionType.ALLOW

    @property
    def requires_approval(self) -> bool:
        return self.decision == PolicyDecisionType.REQUIRES_APPROVAL

    @property
    def is_denied(self) -> bool:
        return self.decision == PolicyDecisionType.DENY


class PolicyRule(BaseModel):
    """Declarative policy configuration rule."""

    rule_id: str = Field(..., description="Unique rule identifier")
    action_type: str = Field(..., description="ActionType name or wildcard '*'")
    environment: str = Field(default="*", description="Environment name or wildcard '*'")
    service: str = Field(default="*", description="Target service or wildcard '*'")
    decision: PolicyDecisionType = Field(..., description="Outcome if rule matches")
    required_role: ActorRole | None = Field(default=None, description="Required approval role")
    risk_class: RiskClass = Field(default=RiskClass.MEDIUM, description="Assigned risk class")
    description: str = Field(default="", description="Documentation of policy intent")
