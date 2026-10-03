"""
Evidence Analysis Node for SentinelOps LangGraph Investigation.

Analyzes collected structured evidence and correlates signals to formulate
candidate failure hypotheses.

Architectural Rule:
Hypotheses must reference valid supporting evidence IDs from the collected evidence.
"""
from __future__ import annotations

from typing import Any, Callable

import structlog

from sentinelops.agent.state import InvestigationState
from sentinelops.domain.contracts.protocols import LLMProvider
from sentinelops.domain.models.investigation import Hypothesis

log = structlog.get_logger(__name__)


def make_analyzer_node(llm_provider: LLMProvider) -> Callable[[InvestigationState], Any]:
    """
    Factory creating the analyzer node with an injected LLMProvider.

    Args:
        llm_provider: Pluggable `LLMProvider` implementation.

    Returns:
        Async node function accepting `InvestigationState`.
    """

    async def analyze_evidence(state: InvestigationState) -> dict[str, Any]:
        incident = state["incident"]
        evidence = state.get("evidence") or []

        hypotheses: list[Hypothesis] = await llm_provider.analyze_hypotheses(
            incident=incident,
            evidence=evidence,
        )

        # Select hypothesis with highest confidence
        selected: Hypothesis | None = None
        if hypotheses:
            selected = max(hypotheses, key=lambda h: h.confidence)

        log.info(
            "investigation.hypotheses_analyzed",
            incident_id=incident.incident_id,
            hypotheses_count=len(hypotheses),
            selected_hypothesis=selected.hypothesis if selected else None,
            confidence=selected.confidence if selected else 0.0,
        )

        return {
            "hypotheses": hypotheses,
            "selected_hypothesis": selected,
        }

    return analyze_evidence
