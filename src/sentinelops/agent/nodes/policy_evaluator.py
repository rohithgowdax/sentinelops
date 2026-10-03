"""
Policy Evaluator Node for SentinelOps.

Enforces deterministic policy evaluation on proposed ActionRequests.
Routes between immediate execution (ALLOW), human approval gate (REQUIRES_APPROVAL),
and rejection (DENY).
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from sentinelops.agent.state import InvestigationState
from sentinelops.approval.service import ApprovalService
from sentinelops.audit.service import AuditService
from sentinelops.domain.models.policy import (
    PolicyDecision,
    PolicyDecisionType,
)
from sentinelops.policy.engine import PolicyEngine

logger = logging.getLogger(__name__)


def make_policy_evaluator_node(
    policy_engine: PolicyEngine,
    approval_service: ApprovalService | None = None,
    audit_service: AuditService | None = None,
) -> Callable[[InvestigationState], dict[str, Any]]:
    """Factory creating policy evaluation LangGraph node."""

    def evaluate_policy(state: InvestigationState) -> dict[str, Any]:
        action_request = state.get("action_request")
        incident = state["incident"]

        if not action_request:
            logger.warning("No ActionRequest in state to evaluate.")
            return {"remediation_status": "error_no_action_request"}

        decision: PolicyDecision = policy_engine.evaluate(action_request)

        updates: dict[str, Any] = {
            "policy_decision": decision,
        }

        if audit_service:
            audit_service.record(
                event_type="policy.evaluated",
                incident_id=incident.incident_id,
                action_id=action_request.action_id,
                actor="policy_engine",
                payload={
                    "decision": decision.decision.value,
                    "reason": decision.reason,
                    "risk_class": decision.risk_class.value,
                    "required_role": decision.required_role.value if decision.required_role else None,
                },
            )

        if decision.decision == PolicyDecisionType.DENY:
            updates["remediation_status"] = "denied"
            logger.warning(
                "Policy DENIED action %s on %s: %s",
                action_request.action_id,
                action_request.target.resource_id,
                decision.reason,
            )

        elif decision.decision == PolicyDecisionType.REQUIRES_APPROVAL:
            updates["remediation_status"] = "awaiting_approval"
            if approval_service:
                approval = approval_service.create_request(action_request, decision)
                updates["approval_status"] = approval.status
                if audit_service:
                    audit_service.record(
                        event_type="approval.requested",
                        incident_id=incident.incident_id,
                        action_id=action_request.action_id,
                        actor="system",
                        payload={
                            "approval_id": approval.approval_id,
                            "required_role": approval.required_role.value,
                        },
                    )
            logger.info(
                "Policy REQUIRES APPROVAL for action %s (required role: %s)",
                action_request.action_id,
                decision.required_role.value if decision.required_role else "none",
            )

        elif decision.decision == PolicyDecisionType.ALLOW:
            updates["remediation_status"] = "approved"
            logger.info("Policy ALLOWED action %s for automated execution.", action_request.action_id)

        return updates

    return evaluate_policy


def route_after_policy(state: InvestigationState) -> str:
    """Conditional edge router after policy evaluation."""
    decision = state.get("policy_decision")
    if not decision:
        return "finalize_denied"

    if decision.decision == PolicyDecisionType.DENY:
        return "finalize_denied"
    elif decision.decision == PolicyDecisionType.REQUIRES_APPROVAL:
        return "await_approval"
    elif decision.decision == PolicyDecisionType.ALLOW:
        return "execute_action"

    return "finalize_denied"
