"""
Incident Intake Node for SentinelOps LangGraph Investigation.

Responsibilities:
1. Validates incoming canonical Incident.
2. Initializes investigation state metadata and timestamps.
3. Sets investigation status to `INVESTIGATING`.
4. Establishes iteration bounds and baseline empty lists.

Architectural Invariant:
No diagnosis or speculation occurs in this node.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from sentinelops.agent.state import InvestigationState
from sentinelops.domain.models.investigation import InvestigationStatus

log = structlog.get_logger(__name__)


def incident_intake(state: InvestigationState) -> dict[str, Any]:
    """
    Intake and validate an active incident into the investigation workflow.

    Args:
        state: Current InvestigationState containing the canonical Incident.

    Returns:
        State update dictionary.
    """
    incident = state["incident"]

    if not incident or not incident.incident_id:
        raise ValueError("incident_intake: Invalid or missing canonical incident.")

    now_iso = datetime.now(tz=timezone.utc).isoformat()

    log.info(
        "investigation.intake_completed",
        incident_id=incident.incident_id,
        service=incident.service_name,
        severity=incident.severity.value,
        trigger_rule_id=incident.trigger_rule_id,
    )

    return {
        "status": InvestigationStatus.INVESTIGATING,
        "iteration": 0,
        "current_step": 0,
        "evidence": state.get("evidence") or [],
        "hypotheses": state.get("hypotheses") or [],
        "selected_hypothesis": None,
        "diagnosis": None,
        "confidence": 0.0,
        "verification_result": None,
        "errors": state.get("errors") or [],
        "tool_calls_summary": state.get("tool_calls_summary") or [],
        "start_time_iso": now_iso,
    }
