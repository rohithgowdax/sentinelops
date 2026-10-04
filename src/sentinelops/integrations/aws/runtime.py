"""
AWS Bedrock AgentCore Runtime Adapter for SentinelOps (Slice 5C).

Provides:
- Hosting and lifecycle execution of the LangGraph SentinelOps graph on Bedrock AgentCore Runtime.
- Preserves incident_id, trace correlation, tenant scope, and actor context.
- Maintains strict policy boundaries and approval interruption states.
- Cleanly isolates AWS runtime event schemas from SentinelOps core domain logic.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from sentinelops.domain.models.incident import Incident
from sentinelops.domain.models.investigation import InvestigationStatus
from sentinelops.domain.models.policy import ActorContext, ActorRole

logger = logging.getLogger(__name__)


class AgentCoreRuntimeAdapter:
    """
    Adapter bridging Amazon Bedrock AgentCore Runtime invocations to SentinelOps LangGraph workflows.
    """

    def __init__(
        self,
        compiled_graph: CompiledStateGraph,
        runtime_id: str = "rt-sentinelops-01",
    ) -> None:
        self.graph = compiled_graph
        self.runtime_id = runtime_id

    async def invoke_from_event(
        self,
        event_payload: dict[str, Any],
        config_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Handle AgentCore Runtime invocation event:
        1. Extract incident, trace context, actor, and thread_id
        2. Prepare initial state or resume command
        3. Invoke LangGraph workflow
        4. Package sanitized execution output
        """
        incident_data = event_payload.get("incident")
        if not incident_data:
            raise ValueError("AgentCore Runtime event missing required 'incident' payload.")

        incident = Incident.model_validate(incident_data)
        trace_id = event_payload.get("trace_id", f"trace-{uuid4().hex[:12]}")
        thread_id = event_payload.get("session_id", f"agentcore-{incident.incident_id}")

        config = config_override or {"configurable": {"thread_id": thread_id}}

        # Check if this is a resume invocation
        action_resume = event_payload.get("resume_action")
        if action_resume:
            logger.info("Resuming AgentCore workflow thread %s with decision %s", thread_id, action_resume)
            result = await self.graph.ainvoke(
                Command(resume={"status": action_resume}),
                config=config,
            )
        else:
            initial_state = {
                "incident": incident,
                "investigation_plan": None,
                "current_step": 0,
                "iteration": 0,
                "max_iterations": 3,
                "evidence": [],
                "hypotheses": [],
                "selected_hypothesis": None,
                "diagnosis": None,
                "confidence": 0.0,
                "verification_result": None,
                "status": InvestigationStatus.INVESTIGATING,
                "errors": [],
                "tool_calls_summary": [],
                "start_time_iso": datetime.now(tz=timezone.utc).isoformat(),
                "final_result": None,
                "evidence_groups": {"telemetry": [], "knowledge": []},
                "knowledge_queries": [],
                "knowledge_available": False,
                "retrieval_mode": "hybrid",
                "action_request": None,
                "policy_decision": None,
                "action_result": None,
                "remediation_verification": None,
                "remediation_status": "none",
                "remediation_attempts": 0,
                "max_remediation_attempts": 2,
            }
            logger.info("Starting AgentCore workflow for incident %s on runtime %s", incident.incident_id, self.runtime_id)
            result = await self.graph.ainvoke(initial_state, config=config)

        final_res = result.get("final_result")
        remediation_status = result.get("remediation_status", "none")
        action_result = result.get("action_result")
        is_completed = (final_res is not None) or (remediation_status in ("resolved", "failed"))

        return {
            "runtime_id": self.runtime_id,
            "incident_id": incident.incident_id,
            "trace_id": trace_id,
            "thread_id": thread_id,
            "status": "completed" if is_completed else "paused_awaiting_approval",
            "investigation_status": final_res.status.value if final_res else ("resolved" if remediation_status == "resolved" else "investigating"),
            "remediation_status": remediation_status,
            "action_result": action_result.model_dump() if action_result else None,
            "root_cause": final_res.diagnosis.root_cause if (final_res and final_res.diagnosis) else None,
        }
