"""
Verification Node and Conditional Edge Router for SentinelOps LangGraph.

Responsibilities:
1. `verify_diagnosis`: Audits the candidate diagnosis against collected evidence.
2. `route_after_verification`: Conditional edge deciding whether to finalize or loop back to collect more evidence.

Loop Bounding:
Guarantees that the loop terminates when `iteration >= max_iterations`.
"""
from __future__ import annotations

from typing import Any, Callable

import structlog

from sentinelops.agent.state import InvestigationState
from sentinelops.domain.contracts.protocols import LLMProvider
from sentinelops.domain.models.investigation import VerificationResult

log = structlog.get_logger(__name__)


def make_verifier_node(llm_provider: LLMProvider) -> Callable[[InvestigationState], Any]:
    """
    Factory creating the verification node with an injected LLMProvider.

    Args:
        llm_provider: Pluggable `LLMProvider` implementation.

    Returns:
        Async node function accepting `InvestigationState`.
    """

    async def verify_diagnosis(state: InvestigationState) -> dict[str, Any]:
        incident = state["incident"]
        evidence = state.get("evidence") or []
        diag = state.get("diagnosis")

        if not diag:
            verification = VerificationResult(
                is_verified=False,
                confidence=0.0,
                reason="No candidate diagnosis was produced.",
                missing_evidence=["diagnosis"],
            )
            return {"verification_result": verification}

        verification = await llm_provider.verify_diagnosis(
            incident=incident,
            evidence=evidence,
            diagnosis=diag,
        )

        log.info(
            "investigation.diagnosis_verified",
            incident_id=incident.incident_id,
            is_verified=verification.is_verified,
            confidence=verification.confidence,
            reason=verification.reason,
        )

        return {"verification_result": verification}

    return verify_diagnosis


def route_after_verification(state: InvestigationState) -> str:
    """
    Conditional routing function for LangGraph verification gate.

    Branches:
    - If `verification_result.is_verified`: route to 'finalize'.
    - If unverified AND `iteration < max_iterations`: route back to 'collect_evidence'.
    - If unverified AND `iteration >= max_iterations`: route to 'finalize'.

    Args:
        state: Current `InvestigationState`.

    Returns:
        Target node name ('finalize' or 'collect_evidence').
    """
    verification = state.get("verification_result")
    iteration = state.get("iteration", 1)
    max_iters = state.get("max_iterations", 3)

    if verification and verification.is_verified:
        log.info("routing.decision", branch="verified_finalize", iteration=iteration)
        return "finalize"

    if iteration < max_iters:
        log.info(
            "routing.decision",
            branch="re_investigate",
            iteration=iteration,
            max_iterations=max_iters,
        )
        return "collect_evidence"

    log.info(
        "routing.decision",
        branch="max_iterations_finalize",
        iteration=iteration,
        max_iterations=max_iters,
    )
    return "finalize"
