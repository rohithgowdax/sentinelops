"""
Diagnosis Synthesis Node for SentinelOps LangGraph Investigation.

Synthesizes supporting evidence and the selected hypothesis into a structured root cause Diagnosis.

Architectural Rule:
The diagnosis MUST reference supporting evidence IDs. No invented evidence IDs permitted.
"""
from __future__ import annotations

from typing import Any, Callable

import structlog

from sentinelops.agent.state import InvestigationState
from sentinelops.domain.contracts.protocols import LLMProvider
from sentinelops.domain.models.investigation import Diagnosis

log = structlog.get_logger(__name__)


def make_diagnoser_node(llm_provider: LLMProvider) -> Callable[[InvestigationState], Any]:
    """
    Factory creating the diagnosis node with an injected LLMProvider.

    Args:
        llm_provider: Pluggable `LLMProvider` implementation.

    Returns:
        Async node function accepting `InvestigationState`.
    """

    async def diagnose(state: InvestigationState) -> dict[str, Any]:
        incident = state["incident"]
        evidence = state.get("evidence") or []
        selected_hypo = state.get("selected_hypothesis")

        if not selected_hypo:
            log.warning(
                "investigation.diagnose_no_hypothesis",
                incident_id=incident.incident_id,
            )
            return {
                "diagnosis": None,
                "confidence": 0.0,
            }

        diagnosis_result: Diagnosis = await llm_provider.generate_diagnosis(
            incident=incident,
            evidence=evidence,
            hypothesis=selected_hypo,
        )

        log.info(
            "investigation.diagnosis_generated",
            incident_id=incident.incident_id,
            root_cause=diagnosis_result.root_cause,
            confidence=diagnosis_result.confidence,
            supporting_evidence=diagnosis_result.supporting_evidence,
        )

        return {
            "diagnosis": diagnosis_result,
            "confidence": diagnosis_result.confidence,
        }

    return diagnose
