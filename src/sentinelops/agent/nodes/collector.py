"""
Evidence Collection Node for SentinelOps LangGraph Investigation.

Executes planned capability queries via:
1. `TelemetryEvidenceProvider`: Queries live telemetry, baseline comparisons, and trigger context.
2. `KnowledgeProvider`: Queries organizational runbooks, architecture, policies, and postmortems.

Architectural Invariants:
- Never imports Qdrant or SQL libraries directly.
- Keeps evidence grouped by source ('telemetry', 'knowledge').
- Gracefully handles knowledge unavailability without failing the telemetry investigation.
"""
from __future__ import annotations

from typing import Any, Callable

import structlog

from sentinelops.agent.state import InvestigationState
from sentinelops.domain.contracts.protocols import (
    KnowledgeProvider,
    LLMProvider,
    TelemetryEvidenceProvider,
)
from sentinelops.domain.models.investigation import InvestigationEvidence
from sentinelops.domain.models.knowledge import KnowledgeQuery, RetrievalMode

log = structlog.get_logger(__name__)


def make_collector_node(
    evidence_provider: TelemetryEvidenceProvider,
    knowledge_provider: KnowledgeProvider | None = None,
    llm_provider: LLMProvider | None = None,
) -> Callable[[InvestigationState], Any]:
    """
    Factory creating the evidence collector node with capability providers.

    Args:
        evidence_provider: Pluggable `TelemetryEvidenceProvider` implementation.
        knowledge_provider: Optional `KnowledgeProvider` for runbook/postmortem retrieval.
        llm_provider: Optional `LLMProvider` for generating contextual search queries.

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
        knowledge_queries_executed: list[str] = list(state.get("knowledge_queries") or [])
        knowledge_available = state.get("knowledge_available", True)
        retrieval_mode_str = state.get("retrieval_mode") or "hybrid"

        try:
            retrieval_mode = RetrievalMode(retrieval_mode_str)
        except ValueError:
            retrieval_mode = RetrievalMode.HYBRID

        # ── 1. Telemetry Evidence Collection ──────────────────────────────────
        target_metric = "http.error_rate"
        if incident.initial_evidence:
            for item in incident.initial_evidence:
                if "http.latency" in item.description or "latency" in item.description:
                    target_metric = "http.latency.p99"
                elif "http.error" in item.description or "error" in item.description:
                    target_metric = "http.error_rate"

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
                            kind="telemetry",
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
                            kind="telemetry",
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
                            kind="telemetry",
                        )
                    )

            except Exception as exc:
                err_msg = f"Evidence collection error for step '{step.id}': {exc}"
                log.error("collector.step_error", error=err_msg)
                errors.append(err_msg)

        # ── 2. Knowledge Retrieval (Slice 3) ──────────────────────────────────
        if knowledge_provider is not None:
            # Generate knowledge queries
            queries_to_run: list[KnowledgeQuery] = []
            if llm_provider is not None and hasattr(llm_provider, "generate_knowledge_queries"):
                try:
                    telemetry_ev = [e for e in existing_evidence if getattr(e, "kind", "telemetry") != "knowledge"]
                    queries_to_run = await llm_provider.generate_knowledge_queries(
                        incident=incident,
                        plan=plan,
                        telemetry_evidence=telemetry_ev,
                    )
                except Exception as exc:
                    log.warning("collector.llm_knowledge_query_failed", error=str(exc))

            if not queries_to_run:
                queries_to_run = [
                    KnowledgeQuery(
                        query=f"{incident.service_name} {target_metric} troubleshooting",
                        service=incident.service_name,
                        limit=3,
                        mode=retrieval_mode,
                    ),
                    KnowledgeQuery(
                        query=f"{incident.title} runbook postmortem",
                        limit=3,
                        mode=retrieval_mode,
                    ),
                ]

            for q in queries_to_run:
                q.mode = retrieval_mode
                knowledge_queries_executed.append(q.query)
                try:
                    results = await knowledge_provider.search(q)
                    tool_calls.append({
                        "tool": "knowledge_provider.search",
                        "iteration": current_iteration,
                        "query": q.query,
                        "mode": q.mode.value,
                        "results_count": len(results),
                    })

                    # Deduplicate chunks already collected
                    existing_chunk_ids = {
                        e.chunk_id for e in existing_evidence if getattr(e, "chunk_id", None)
                    }

                    for res in results:
                        if res.chunk_id in existing_chunk_ids:
                            continue
                        existing_chunk_ids.add(res.chunk_id)

                        existing_evidence.append(
                            InvestigationEvidence(
                                evidence_id=f"EK{len(existing_evidence) + 1:02d}",
                                incident_id=incident.incident_id,
                                source_type="knowledge",
                                source_ref=res.document_id,
                                timestamp_window={"time": incident.created_at.isoformat()},
                                resource=res.service or incident.service_name,
                                signal="organizational_knowledge",
                                observation={
                                    "title": res.title,
                                    "section": res.section,
                                    "document_type": res.document_type.value,
                                    "score": res.score,
                                    "rank": res.rank,
                                    "metadata": res.metadata,
                                },
                                relevance=f"Operational knowledge reference: '{res.title}' ({res.section})",
                                kind="knowledge",
                                document_id=res.document_id,
                                chunk_id=res.chunk_id,
                                source=res.source,
                                document_type=res.document_type.value,
                                retrieval_score=res.score,
                                rank=res.rank,
                                content_snippet=res.content[:500],
                            )
                        )
                except Exception as exc:
                    err_msg = f"Knowledge retrieval error for query '{q.query}': {exc}"
                    log.warning("collector.knowledge_error", error=err_msg)
                    errors.append(err_msg)
                    knowledge_available = False

        # Group evidence items by source
        telemetry_items = [e for e in existing_evidence if getattr(e, "kind", "telemetry") != "knowledge"]
        knowledge_items = [e for e in existing_evidence if getattr(e, "kind", "telemetry") == "knowledge"]
        evidence_groups = {
            "telemetry": telemetry_items,
            "knowledge": knowledge_items,
        }

        log.info(
            "investigation.evidence_collected",
            incident_id=incident.incident_id,
            iteration=current_iteration,
            telemetry_count=len(telemetry_items),
            knowledge_count=len(knowledge_items),
            knowledge_available=knowledge_available,
        )

        return {
            "evidence": existing_evidence,
            "evidence_groups": evidence_groups,
            "knowledge_queries": knowledge_queries_executed,
            "knowledge_available": knowledge_available,
            "retrieval_mode": retrieval_mode.value,
            "iteration": current_iteration,
            "tool_calls_summary": tool_calls,
            "errors": errors,
        }

    return collect_evidence
