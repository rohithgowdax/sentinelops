"""
Finalizer Node for SentinelOps LangGraph Investigation.

Synthesizes the terminal `InvestigationResult` recording:
- Incident ID
- Final status (DIAGNOSED, INSUFFICIENT_EVIDENCE, INVESTIGATION_FAILED)
- Diagnosis and confidence
- Supporting structured evidence
- Execution duration and iteration count
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from sentinelops.agent.state import InvestigationState
from sentinelops.domain.models.investigation import (
    InvestigationResult,
    InvestigationStatus,
)

log = structlog.get_logger(__name__)


def finalize(state: InvestigationState) -> dict[str, Any]:
    """
    Produce the immutable terminal InvestigationResult record.

    Args:
        state: Final `InvestigationState`.

    Returns:
        State update dictionary containing `final_result`.
    """
    incident = state["incident"]
    plan = state.get("investigation_plan")
    diag = state.get("diagnosis")
    verification = state.get("verification_result")
    evidence = state.get("evidence") or []
    tool_calls = state.get("tool_calls_summary") or []
    iterations = state.get("iteration", 1)

    # Compute execution duration
    now = datetime.now(tz=timezone.utc)
    duration = 0.0
    start_iso = state.get("start_time_iso")
    if start_iso:
        try:
            start_dt = datetime.fromisoformat(start_iso)
            duration = max(0.0, (now - start_dt).total_seconds())
        except Exception:
            pass

    # Determine terminal status
    if verification and verification.is_verified and diag:
        status = InvestigationStatus.DIAGNOSED
        confidence = diag.confidence
        failure_reason = None
    else:
        status = InvestigationStatus.INSUFFICIENT_EVIDENCE
        confidence = diag.confidence if diag else 0.0
        failure_reason = (
            verification.reason
            if verification
            else "Investigation terminated without sufficient verified evidence."
        )

    telemetry_ev = [e for e in evidence if getattr(e, "kind", "telemetry") != "knowledge"]
    knowledge_ev = [e for e in evidence if getattr(e, "kind", "telemetry") == "knowledge"]

    result = InvestigationResult(
        incident_id=incident.incident_id,
        status=status,
        diagnosis=diag,
        confidence=confidence,
        supporting_evidence=evidence,
        telemetry_evidence=telemetry_ev,
        knowledge_evidence=knowledge_ev,
        retrieval_queries=state.get("knowledge_queries") or [],
        retrieval_mode=state.get("retrieval_mode"),
        investigation_steps=plan.steps if plan else [],
        tool_calls_summary=tool_calls,
        duration_seconds=round(duration, 3),
        iteration_count=iterations,
        failure_reason=failure_reason,
        completed_at=now,
    )


    log.info(
        "investigation.finalized",
        incident_id=incident.incident_id,
        status=status.value,
        confidence=confidence,
        iterations=iterations,
        duration_seconds=result.duration_seconds,
    )

    return {
        "status": status,
        "final_result": result,
    }
