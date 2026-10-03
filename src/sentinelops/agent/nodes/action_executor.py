"""
Action Execution Nodes for SentinelOps Remediation Workflow.

Implements:
- `await_approval_node`: Interruption / pause point waiting for human operator approval.
- `execute_action_node`: Pre-execution revalidation and invocation of the configured ActionProvider.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from langgraph.types import interrupt

from sentinelops.agent.state import InvestigationState
from sentinelops.approval.service import ApprovalService, ApprovalStatus
from sentinelops.audit.service import AuditService
from sentinelops.capabilities.actions.protocol import ActionProvider
from sentinelops.domain.models.action import ActionResult, ActionStatus

logger = logging.getLogger(__name__)


def make_await_approval_node(
    approval_service: ApprovalService | None = None,
    audit_service: AuditService | None = None,
) -> Callable[[InvestigationState], dict[str, Any]]:
    """
    Node that pauses execution for human approval.
    Uses LangGraph's interrupt() or checkpoint mechanism.
    """

    def await_approval(state: InvestigationState) -> dict[str, Any]:
        action_request = state.get("action_request")
        if not action_request:
            return {"remediation_status": "error_no_action"}

        action_id = action_request.action_id
        app = approval_service.get_approval(action_id) if approval_service else None

        # If already approved prior to resuming (e.g. via Approval API before graph resume)
        if app and app.status == ApprovalStatus.APPROVED:
            logger.info("Resuming execution: Action %s has been APPROVED by %s", action_id, app.resolved_by)
            return {"remediation_status": "approved"}

        if app and app.status == ApprovalStatus.REJECTED:
            logger.info("Action %s was REJECTED by human operator.", action_id)
            return {"remediation_status": "rejected"}

        # Pause execution using LangGraph interrupt()
        logger.info("Interrupting graph execution waiting for approval on action %s", action_id)
        human_decision = interrupt({
            "action_id": action_id,
            "incident_id": action_request.incident_id,
            "action_type": action_request.action_type.value,
            "target": action_request.target.resource_id,
            "parameters": action_request.parameters,
            "required_role": app.required_role.value if app else "incident_commander",
            "message": "Human approval required for high-risk action.",
        })

        # Process resume payload if provided directly
        if isinstance(human_decision, dict):
            status = human_decision.get("status")
            if status == "approved":
                return {"remediation_status": "approved"}
            elif status == "rejected":
                return {"remediation_status": "rejected"}

        # Re-check approval service after resume
        if approval_service:
            app_after = approval_service.get_approval(action_id)
            if app_after and app_after.status == ApprovalStatus.APPROVED:
                return {"remediation_status": "approved"}
            elif app_after and app_after.status == ApprovalStatus.REJECTED:
                return {"remediation_status": "rejected"}

        return {"remediation_status": "awaiting_approval"}

    return await_approval


def route_after_approval(state: InvestigationState) -> str:
    """Route based on human approval resolution."""
    status = state.get("remediation_status")
    if status == "approved":
        return "execute_action"
    elif status == "rejected":
        return "finalize_denied"
    return "finalize_denied"


def make_action_executor_node(
    action_provider: ActionProvider,
    approval_service: ApprovalService | None = None,
    audit_service: AuditService | None = None,
) -> Callable[[InvestigationState], Any]:
    """Factory creating action execution LangGraph node."""

    async def execute_action(state: InvestigationState) -> dict[str, Any]:
        action_request = state.get("action_request")
        incident = state["incident"]
        decision = state.get("policy_decision")

        if not action_request:
            logger.error("No ActionRequest present to execute.")
            return {"remediation_status": "execution_failed"}

        action_id = action_request.action_id

        # 1. Pre-execution revalidation if policy required approval
        if decision and decision.requires_approval:
            if not approval_service:
                logger.error("Action requires approval but ApprovalService is not configured.")
                return {"remediation_status": "execution_failed"}

            reval_ok, reval_msg = approval_service.revalidate_for_execution(action_request)
            if not reval_ok:
                logger.error("Action revalidation failed: %s", reval_msg)
                if audit_service:
                    audit_service.record(
                        event_type="action.revalidation_failed",
                        incident_id=incident.incident_id,
                        action_id=action_id,
                        actor="system",
                        payload={"reason": reval_msg},
                    )
                return {
                    "remediation_status": "revalidation_failed",
                    "action_result": ActionResult(
                        action_id=action_id,
                        status=ActionStatus.REJECTED,
                        provider=action_provider.provider_name,
                        error=reval_msg,
                    ),
                }

            if audit_service:
                audit_service.record(
                    event_type="action.revalidated",
                    incident_id=incident.incident_id,
                    action_id=action_id,
                    actor="system",
                    payload={"status": "revalidated"},
                )

        # 2. Record action started audit
        if audit_service:
            audit_service.record(
                event_type="action.started",
                incident_id=incident.incident_id,
                action_id=action_id,
                actor="sentinelops-agent",
                payload={"provider": action_provider.provider_name},
            )

        # 3. Execute via ActionProvider
        logger.info("Executing action %s via provider '%s'", action_id, action_provider.provider_name)
        result: ActionResult = await action_provider.execute(action_request)

        # 4. Record action completed audit
        if audit_service:
            audit_service.record(
                event_type="action.completed",
                incident_id=incident.incident_id,
                action_id=action_id,
                actor="action_provider",
                payload={"status": result.status.value, "error": result.error},
            )

        return {
            "action_result": result,
            "remediation_status": "executing" if result.status == ActionStatus.SUCCEEDED else "execution_failed",
        }

    return execute_action
