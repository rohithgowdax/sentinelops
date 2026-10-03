"""
Evidence Collection Node for SentinelOps LangGraph Investigation.

Executes planned capability queries via `TelemetryEvidenceProvider`.
Transforms structured tool results into canonical `InvestigationEvidence` models.

Architectural Rule:
This node only interacts with `TelemetryEvidenceProvider` capability interface,
never executing raw SQL or Redis operations directly.
"""
from __future__ import annotations

from typing import Any, Callable

import structlog

from sentinelops.agent.state import InvestigationState
from sentinelops.domain.contracts.protocols import TelemetryEvidenceProvider
from sentinelops.domain.models.investigation import InvestigationEvidence

log = structlog.get_logger(__name__)


def make_collector_node(
    evidence_provider: TelemetryEvidenceProvider,
) -> Callable[[InvestigationState], Any]:
    """
    Factory creating the evidence collector node with an injected TelemetryEvidenceProvider.

    Args:
        evidence_provider: Pluggable `TelemetryEvidenceProvider` implementation.

    Returns:
        Async node function accepting `InvestigationState`.
    """

    async def collect_evidence(state: InvestigationState) -> dict[str, Any]:
        incident = state["incident"]
        plan = state.get("investigation_plan")
        current_iteration = state.get("iteration", 0) + 1
        existing_evidence = list(state.get("evidence") or [])
        tool_calls = list(state.get("tool_calls_summary") or [])
        errors = list(state.get("errors") or [])

        # Default fallback metric name
        target_metric = "http.error_rate"
        if incident.initial_evidence:
            for item in incident.initial_evidence:
                if "http.latency" in item.description or "latency" in item.description:
                    target_metric = "http.latency.p99"
                elif "http.error" in item.description or "error" in item.description:
                    target_metric = "http.error_rate"

        # Determine steps to execute
        steps_to_run = plan.steps if plan and plan.steps else []

        for step in steps_to_run:
            try:
                if step.capability == "trigger_context":
                    res = await evidence_provider.get_incident_trigger_context(incident)
                    tool_calls.append({
                        "tool": "get_incident_trigger_context",
                        "iteration": current_iteration,
                        "params": {"incident_id": incident.incident_id},
                    })

                    existing_evidence.append(
                        InvestigationEvidence(
                            evidence_id=f"E{len(existing_evidence) + 1:02d}",
                            incident_id=incident.incident_id,
                            source_type="trigger_context",
                            source_ref=incident.trigger_rule_id or "rule-trigger",
                            timestamp_window={"time": incident.created_at.isoformat()},
                            resource=incident.service_name,
                            signal=target_metric,
                            observation={
                                "trigger_rule_id": incident.trigger_rule_id,
                                "trigger_rule_name": incident.trigger_rule_name,
                                "initial_evidence": res.get("initial_evidence", []),
                                "severity": incident.severity.value,
                            },
                            relevance=f"Initial incident trigger context by rule '{incident.trigger_rule_id}'",
                        )
                    )

                elif step.capability == "telemetry":
                    metric_name = step.params.get("metric_name", target_metric)
                    lookback = step.params.get("lookback_seconds", 300)
                    res = await evidence_provider.query_recent_telemetry(
                        service_name=incident.service_name,
                        metric_name=metric_name,
                        lookback_seconds=lookback,
                    )
                    tool_calls.append({
                        "tool": "query_recent_telemetry",
                        "iteration": current_iteration,
                        "params": {
                            "service_name": incident.service_name,
                            "metric_name": metric_name,
                            "lookback": lookback,
                        },
                    })

                    existing_evidence.append(
                        InvestigationEvidence(
                            evidence_id=f"E{len(existing_evidence) + 1:02d}",
                            incident_id=incident.incident_id,
                            source_type="telemetry",
                            source_ref=metric_name,
                            timestamp_window=res.get("window", {}),
                            resource=incident.service_name,
                            signal=metric_name,
                            observation=res,
                            relevance=(
                                f"Observed recent {metric_name} (avg: {res.get('observed_avg')}, "
                                f"max: {res.get('observed_max')})"
                            ),
                            raw_reference=res.get("raw_references", [None])[0],
                        )
                    )

                elif step.capability == "baseline":
                    metric_name = step.params.get("metric_name", target_metric)
                    curr_win = step.params.get("current_window_seconds", 120)
                    base_win = step.params.get("baseline_window_seconds", 600)
                    res = await evidence_provider.compare_telemetry_baseline(
                        service_name=incident.service_name,
                        metric_name=metric_name,
                        current_window_seconds=curr_win,
                        baseline_window_seconds=base_win,
                    )
                    tool_calls.append({
                        "tool": "compare_telemetry_baseline",
                        "iteration": current_iteration,
                        "params": {
                            "service_name": incident.service_name,
                            "metric_name": metric_name,
                            "current_window": curr_win,
                            "baseline_window": base_win,
                        },
                    })

                    existing_evidence.append(
                        InvestigationEvidence(
                            evidence_id=f"E{len(existing_evidence) + 1:02d}",
                            incident_id=incident.incident_id,
                            source_type="baseline_comparison",
                            source_ref=metric_name,
                            timestamp_window=res.get("current_window", {}),
                            resource=incident.service_name,
                            signal=metric_name,
                            observation=res,
                            relevance=(
                                f"{metric_name} elevation ratio {res.get('elevation_ratio')}x "
                                f"compared to historical baseline {res.get('baseline_avg')}"
                            ),
                        )
                    )

            except Exception as exc:
                err_msg = f"Evidence collection error for step '{step.id}': {exc}"
                log.error("collector.step_error", error=err_msg)
                errors.append(err_msg)

        log.info(
            "investigation.evidence_collected",
            incident_id=incident.incident_id,
            iteration=current_iteration,
            evidence_count=len(existing_evidence),
        )

        return {
            "evidence": existing_evidence,
            "iteration": current_iteration,
            "tool_calls_summary": tool_calls,
            "errors": errors,
        }

    return collect_evidence
