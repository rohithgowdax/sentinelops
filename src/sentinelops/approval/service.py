"""
Approval Service and Lifecycle Management for Human-in-the-Loop Remediation.

Invariants:
- Approvals are one-time, auditable, incident-bound, and strictly bound to the exact ActionRequest.
- Requires authorized actor role matching or exceeding the policy requirement.
- Revalidates request integrity before execution.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from sentinelops.domain.models.action import ActionRequest
from sentinelops.domain.models.policy import (
    ActorContext,
    ActorRole,
    PolicyDecision,
    PolicyDecisionType,
)

logger = logging.getLogger(__name__)


class ApprovalStatus(str, Enum):
    """Lifecycle state of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalRequest(BaseModel):
    """Authoritative record of a human approval request for an ActionRequest."""

    approval_id: str = Field(default_factory=lambda: f"APP-{uuid4().hex[:8]}")
    action_id: str = Field(...)
    incident_id: str = Field(...)
    action_request: ActionRequest = Field(...)
    policy_decision: PolicyDecision = Field(...)
    status: ApprovalStatus = Field(default=ApprovalStatus.PENDING)
    required_role: ActorRole = Field(...)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    resolved_at: datetime | None = Field(default=None)
    resolved_by: str | None = Field(default=None)
    resolved_by_role: ActorRole | None = Field(default=None)
    resolution_reason: str | None = Field(default=None)
    is_consumed: bool = Field(default=False, description="One-time use consumption flag")


class ApprovalService:
    """Manages creation, query, resolution, and revalidation of remediation approvals."""

    def __init__(self) -> None:
        # action_id -> ApprovalRequest
        self._approvals: dict[str, ApprovalRequest] = {}

    def create_request(
        self,
        request: ActionRequest,
        decision: PolicyDecision,
    ) -> ApprovalRequest:
        """Create a pending approval request for a policy-gated action."""
        required = decision.required_role or ActorRole.OPERATOR
        approval = ApprovalRequest(
            action_id=request.action_id,
            incident_id=request.incident_id,
            action_request=request,
            policy_decision=decision,
            required_role=required,
        )
        self._approvals[request.action_id] = approval
        logger.info(
            "Created approval request %s for action %s (required role: %s)",
            approval.approval_id,
            request.action_id,
            required.value,
        )
        return approval

    def get_approval(self, action_id: str) -> ApprovalRequest | None:
        return self._approvals.get(action_id)

    def list_approvals(self, status: ApprovalStatus | None = None) -> list[ApprovalRequest]:
        if status:
            return [a for a in self._approvals.values() if a.status == status]
        return list(self._approvals.values())

    def approve(
        self,
        action_id: str,
        actor: ActorContext,
        comment: str = "Approved for execution",
    ) -> tuple[bool, str, ApprovalRequest | None]:
        """
        Authorize and approve an action request.
        Validates actor role against the required role.
        """
        approval = self._approvals.get(action_id)
        if not approval:
            return False, f"Approval request for action '{action_id}' not found.", None

        if approval.status != ApprovalStatus.PENDING:
            return False, f"Approval is already resolved (status: {approval.status.value}).", approval

        # Role verification
        if not actor.has_sufficient_role(approval.required_role):
            return False, (
                f"Unauthorized: Actor '{actor.actor_id}' with role '{actor.role.value}' "
                f"lacks required role '{approval.required_role.value}'."
            ), approval

        approval.status = ApprovalStatus.APPROVED
        approval.resolved_at = datetime.now(tz=timezone.utc)
        approval.resolved_by = actor.actor_id
        approval.resolved_by_role = actor.role
        approval.resolution_reason = comment

        logger.info("Approval %s APPROVED by actor %s (%s)", approval.approval_id, actor.actor_id, actor.role.value)
        return True, "Action approved successfully.", approval

    def reject(
        self,
        action_id: str,
        actor: ActorContext,
        reason: str = "Rejected by operator",
    ) -> tuple[bool, str, ApprovalRequest | None]:
        """Reject an action request."""
        approval = self._approvals.get(action_id)
        if not approval:
            return False, f"Approval request for action '{action_id}' not found.", None

        if approval.status != ApprovalStatus.PENDING:
            return False, f"Approval is already resolved (status: {approval.status.value}).", approval

        approval.status = ApprovalStatus.REJECTED
        approval.resolved_at = datetime.now(tz=timezone.utc)
        approval.resolved_by = actor.actor_id
        approval.resolved_by_role = actor.role
        approval.resolution_reason = reason

        logger.info("Approval %s REJECTED by actor %s: %s", approval.approval_id, actor.actor_id, reason)
        return True, "Action rejected.", approval

    def revalidate_for_execution(self, incoming_request: ActionRequest) -> tuple[bool, str]:
        """
        Revalidate approval immediately prior to execution.
        Verifies:
        1. Approval exists and is APPROVED.
        2. Parameters match approved request exactly (no tampering).
        3. One-time use: approval has not been consumed.
        """
        action_id = incoming_request.action_id
        approval = self._approvals.get(action_id)
        if not approval:
            return False, f"No approval record found for action '{action_id}'."

        if approval.status != ApprovalStatus.APPROVED:
            return False, f"Approval status is '{approval.status.value}', not 'approved'."

        if approval.is_consumed:
            return False, f"Approval for action '{action_id}' has already been consumed (one-time use violation)."

        # Validate exact parameter and target integrity
        orig = approval.action_request
        if orig.action_type != incoming_request.action_type:
            return False, f"Action type mismatch: approved '{orig.action_type}', incoming '{incoming_request.action_type}'."

        if orig.target.resource_id != incoming_request.target.resource_id:
            return False, f"Target resource mismatch: approved '{orig.target.resource_id}', incoming '{incoming_request.target.resource_id}'."

        if orig.parameters != incoming_request.parameters:
            return False, f"Action parameters altered after approval: approved {orig.parameters}, incoming {incoming_request.parameters}."

        if orig.environment != incoming_request.environment:
            return False, f"Environment mismatch: approved '{orig.environment}', incoming '{incoming_request.environment}'."

        # Mark as consumed upon successful revalidation
        approval.is_consumed = True
        return True, "Approval revalidation successful. Execution authorized."
