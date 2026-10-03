"""
Investigation Planner Node for SentinelOps LangGraph.

Formulates a structured `InvestigationPlan` using available capability abstractions.

Architectural Rule:
The plan references generic capabilities ('telemetry', 'baseline', 'trigger_context')
rather than vendor-specific technologies ('Prometheus', 'Datadog', 'Kubernetes').
"""
from __future__ import annotations

from typing import Any, Callable

import structlog

from sentinelops.agent.state import InvestigationState
from sentinelops.domain.contracts.protocols import LLMProvider
from sentinelops.domain.models.investigation import InvestigationPlan

log = structlog.get_logger(__name__)


def make_planner_node(llm_provider: LLMProvider) -> Callable[[InvestigationState], Any]:
    """
    Factory creating the planner node with an injected LLMProvider.

    Args:
        llm_provider: Pluggable `LLMProvider` implementation.

    Returns:
        Async node function accepting `InvestigationState`.
    """

    async def build_investigation_plan(state: InvestigationState) -> dict[str, Any]:
        incident = state["incident"]
        available_caps = ["telemetry", "baseline", "trigger_context"]

        plan: InvestigationPlan = await llm_provider.generate_plan(
            incident=incident,
            available_capabilities=available_caps,
        )

        log.info(
            "investigation.plan_created",
            incident_id=incident.incident_id,
            steps_count=len(plan.steps),
            steps=[s.id for s in plan.steps],
        )

        return {
            "investigation_plan": plan,
            "current_step": 0,
        }

    return build_investigation_plan
