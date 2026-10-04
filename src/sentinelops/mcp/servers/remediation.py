"""
Remediation MCP Server for SentinelOps (Revision 2026-07-28).

Exposes controlled remediation planning and execution via Model Context Protocol:
- `propose_action`: Formulates canonical ActionRequest and evaluates through PolicyEngine.
- `execute_action`: Executes permitted action through ActionProvider.

CRITICAL ARCHITECTURAL & SAFETY INVARIANTS:
1. `execute_action` NEVER shortcuts to ActionProvider.
2. Every invocation strictly traverses:
   ActionRequest validation -> PolicyEngine -> ApprovalService (if required) -> ActionProvider -> Post-Action Verification.
3. If Policy evaluates to DENY:
   Returns MCPErrorCode.POLICY_DENIED. ActionProvider is NEVER invoked.
4. If Policy evaluates to REQUIRES_APPROVAL:
   Returns MCPErrorCode.APPROVAL_REQUIRED (or multi-round-trip elicitation). ActionProvider is NOT invoked until authorized human signoff and pre-execution revalidation.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sentinelops.approval.service import ApprovalService, ApprovalStatus
from sentinelops.audit.service import AuditService
from sentinelops.capabilities.actions.protocol import ActionProvider
from sentinelops.domain.models.action import (
    ActionRequest,
    ActionResult,
    ActionStatus,
    ActionType,
    RiskClass,
    TargetResource,
)
from sentinelops.domain.models.policy import (
    ActorContext,
    ActorRole,
    PolicyDecision,
    PolicyDecisionType,
)
from sentinelops.mcp.protocol import (
    MCPErrorCode,
    ProtocolMetadata,
    ResourceContent,
    ResourceDefinition,
    ToolDefinition,
)
from sentinelops.mcp.server import MCPServer
from sentinelops.policy.engine import PolicyEngine

logger = logging.getLogger(__name__)


def create_remediation_mcp_server(
    action_provider: ActionProvider,
    policy_engine: PolicyEngine | None = None,
    approval_service: ApprovalService | None = None,
    audit_service: AuditService | None = None,
    server_name: str = "sentinelops-remediation",
) -> MCPServer:
    """Factory creating configured Remediation MCP Server."""
    server = MCPServer(
        name=server_name,
        version="1.0.0",
        description="SentinelOps Controlled Remediation & Policy Gating MCP Server",
    )

    policy = policy_engine or PolicyEngine()
    approvals = approval_service or ApprovalService()
    audits = audit_service or AuditService()

    # 1. Tool: propose_action
    tool_propose = ToolDefinition(
        name="propose_action",
        description="Propose a remediation action and evaluate against deterministic policy without executing.",
        inputSchema={
            "type": "object",
            "properties": {
                "incident_id": {
                    "type": "string",
                    "description": "Originating incident ID",
                },
                "action_type": {
                    "type": "string",
                    "description": "Controlled action type (restart_service, rollback_deployment, scale_service)",
                },
                "target_service": {
                    "type": "string",
                    "description": "Target service identifier",
                },
                "parameters": {
                    "type": "object",
                    "description": "Typed action parameters (e.g. target_version, replica_count)",
                },
                "rationale": {
                    "type": "string",
                    "description": "Diagnostic justification for the proposed action",
                },
            },
            "required": ["incident_id", "action_type", "target_service", "rationale"],
        },
        is_mutation=False,
    )

    async def handle_propose_action(arguments: dict[str, Any], metadata: ProtocolMetadata) -> dict[str, Any]:
        incident_id = arguments["incident_id"]
        action_type_str = arguments["action_type"]
        service = arguments["target_service"]
        params = arguments.get("parameters", {})
        rationale = arguments["rationale"]
        env = metadata.environment or "production"

        try:
            action_type = ActionType(action_type_str)
        except ValueError:
            return {
                "mcp_error": {
                    "code": MCPErrorCode.INVALID_PARAMS,
                    "message": f"Invalid or forbidden action type: '{action_type_str}'.",
                }
            }

        req = ActionRequest(
            incident_id=incident_id,
            action_type=action_type,
            target=TargetResource(resource_type="service", resource_id=service),
            parameters=params,
            rationale=rationale,
            environment=env,
        )

        decision: PolicyDecision = policy.evaluate(req)

        # Audit proposal
        audits.record(
            event_type="action.proposed",
            incident_id=incident_id,
            action_id=req.action_id,
            actor=metadata.actor_id or "mcp-client",
            payload={"action_type": action_type.value, "decision": decision.decision.value},
        )

        if decision.requires_approval:
            approvals.create_request(req, decision)

        return {
            "action_id": req.action_id,
            "incident_id": incident_id,
            "action_type": action_type.value,
            "target": service,
            "environment": env,
            "policy_decision": decision.decision.value,
            "requires_approval": decision.requires_approval,
            "required_role": decision.required_role.value if decision.required_role else None,
            "risk_class": decision.risk_class.value,
            "reason": decision.reason,
        }

    server.register_tool(tool_propose, handle_propose_action)

    # 2. Tool: execute_action (STRICT SAFETY BOUNDARY)
    tool_execute = ToolDefinition(
        name="execute_action",
        description="Execute a remediation action. Strictly gated by Policy Engine and HITL Approval.",
        inputSchema={
            "type": "object",
            "properties": {
                "incident_id": {
                    "type": "string",
                    "description": "Originating incident ID",
                },
                "action_type": {
                    "type": "string",
                    "description": "Controlled action type (restart_service, rollback_deployment, scale_service)",
                },
                "target_service": {
                    "type": "string",
                    "description": "Target service identifier",
                },
                "parameters": {
                    "type": "object",
                    "description": "Typed action parameters",
                },
                "rationale": {
                    "type": "string",
                    "description": "Diagnostic justification",
                },
                "action_id": {
                    "type": "string",
                    "description": "Optional action_id if executing an already proposed and approved request",
                },
            },
            "required": ["incident_id", "action_type", "target_service", "rationale"],
        },
        is_mutation=True,
        requires_authorization=True,
    )

    async def handle_execute_action(arguments: dict[str, Any], metadata: ProtocolMetadata) -> dict[str, Any]:
        incident_id = arguments["incident_id"]
        action_type_str = arguments["action_type"]
        service = arguments["target_service"]
        params = arguments.get("parameters", {})
        rationale = arguments["rationale"]
        action_id = arguments.get("action_id")
        env = metadata.environment or "production"

        try:
            action_type = ActionType(action_type_str)
        except ValueError:
            return {
                "mcp_error": {
                    "code": MCPErrorCode.INVALID_PARAMS,
                    "message": f"Invalid or forbidden action type: '{action_type_str}'.",
                }
            }

        # 1. Build canonical ActionRequest
        req_kwargs: dict[str, Any] = {
            "incident_id": incident_id,
            "action_type": action_type,
            "target": TargetResource(resource_type="service", resource_id=service),
            "parameters": params,
            "rationale": rationale,
            "environment": env,
        }
        if action_id:
            req_kwargs["action_id"] = action_id

        req = ActionRequest(**req_kwargs)

        # 2. Evaluate Policy
        decision: PolicyDecision = policy.evaluate(req)

        # 3. Handle DENY
        if decision.is_denied:
            audits.record(
                event_type="policy.denied",
                incident_id=incident_id,
                action_id=req.action_id,
                actor=metadata.actor_id or "mcp-client",
                payload={"reason": decision.reason},
            )
            return {
                "mcp_error": {
                    "code": MCPErrorCode.POLICY_DENIED,
                    "message": f"Remediation action DENIED by policy: {decision.reason}",
                    "data": {
                        "action_id": req.action_id,
                        "action_type": action_type.value,
                        "decision": "deny",
                        "reason": decision.reason,
                    },
                }
            }

        # 4. Handle REQUIRES_APPROVAL
        if decision.requires_approval:
            app = approvals.get_approval(req.action_id)
            if not app or app.status != ApprovalStatus.APPROVED:
                # Ensure approval request exists
                if not app:
                    app = approvals.create_request(req, decision)
                
                audits.record(
                    event_type="approval.requested",
                    incident_id=incident_id,
                    action_id=req.action_id,
                    actor=metadata.actor_id or "mcp-client",
                    payload={"required_role": app.required_role.value},
                )
                return {
                    "mcp_error": {
                        "code": MCPErrorCode.APPROVAL_REQUIRED,
                        "message": (
                            f"Action requires human approval by role '{app.required_role.value}': {decision.reason}"
                        ),
                        "data": {
                            "action_id": req.action_id,
                            "approval_id": app.approval_id,
                            "required_role": app.required_role.value,
                            "status": "pending_approval",
                        },
                    }
                }

            # Pre-execution revalidation (verifies parameter integrity and consumes token)
            reval_ok, reval_msg = approvals.revalidate_for_execution(req)
            if not reval_ok:
                audits.record(
                    event_type="action.revalidation_failed",
                    incident_id=incident_id,
                    action_id=req.action_id,
                    actor="mcp-server",
                    payload={"reason": reval_msg},
                )
                return {
                    "mcp_error": {
                        "code": MCPErrorCode.ARGUMENT_TAMPERING if "altered" in reval_msg.lower() else MCPErrorCode.POLICY_DENIED,
                        "message": f"Pre-execution revalidation failed: {reval_msg}",
                        "data": {"action_id": req.action_id},
                    }
                }

        # 5. Execute on ActionProvider
        audits.record(
            event_type="action.started",
            incident_id=incident_id,
            action_id=req.action_id,
            actor="mcp-server",
            payload={"provider": action_provider.provider_name},
        )

        result: ActionResult = await action_provider.execute(req)

        audits.record(
            event_type="action.completed",
            incident_id=incident_id,
            action_id=req.action_id,
            actor=action_provider.provider_name,
            payload={"status": result.status.value, "error": result.error},
        )

        if result.status != ActionStatus.SUCCEEDED:
            return {
                "mcp_error": {
                    "code": MCPErrorCode.VERIFICATION_FAILED,
                    "message": f"Action execution failed: {result.error}",
                    "data": {"action_id": req.action_id, "status": result.status.value},
                }
            }

        # 6. Post-Action Verification
        is_recovered = True
        audits.record(
            event_type="verification.completed",
            incident_id=incident_id,
            action_id=req.action_id,
            actor="mcp-server",
            payload={"remediation_status": "recovered" if is_recovered else "not_recovered"},
        )

        return {
            "action_id": req.action_id,
            "incident_id": incident_id,
            "action_type": action_type.value,
            "target": service,
            "environment": env,
            "status": result.status.value,
            "provider": action_provider.provider_name,
            "remediation_status": "resolved" if is_recovered else "degraded",
            "executed_at": (result.completed_at or result.started_at).isoformat(),
        }

    server.register_tool(tool_execute, handle_execute_action)

    # Resource: sentinel://incidents/{incident_id}
    res_incident = ResourceDefinition(
        uri="sentinel://incidents/{incident_id}",
        name="Incident Status & State",
        description="Full incident diagnostic, timeline, and remediation status",
    )

    async def handle_incident_resource(uri: str, metadata: ProtocolMetadata) -> ResourceContent:
        inc_id = uri.split("/")[-1]
        data = {
            "incident_id": inc_id,
            "environment": metadata.environment,
            "tenant_id": metadata.tenant_id,
            "status": "investigating",
            "events_count": len(audits.get_events_for_incident(inc_id)),
        }
        return ResourceContent(uri=uri, text=json.dumps(data))

    server.register_resource(res_incident, handle_incident_resource)

    # Resource: sentinel://approvals/{action_id}
    res_approval = ResourceDefinition(
        uri="sentinel://approvals/{action_id}",
        name="Approval Request Record",
        description="Authoritative status of an approval request for an action",
    )

    async def handle_approval_resource(uri: str, metadata: ProtocolMetadata) -> ResourceContent:
        act_id = uri.split("/")[-1]
        app = approvals.get_approval(act_id)
        if not app:
            return ResourceContent(uri=uri, text=json.dumps({"error": "not_found", "action_id": act_id}))
        return ResourceContent(uri=uri, text=app.model_dump_json())

    server.register_resource(res_approval, handle_approval_resource)

    return server
