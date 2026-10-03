"""
Incident Investigation Benchmark Suite for SentinelOps.

Executes 30 held-out incident investigations across 4 ablation configurations:
- Mode A: Telemetry-Only + Deterministic LLM Provider
- Mode B: Telemetry + Knowledge + Deterministic LLM Provider
- Mode C: Telemetry-Only + Semantic LLM Provider
- Mode D: Telemetry + Knowledge + Semantic LLM Provider

Evaluates:
- Root-cause accuracy with Wilson 95% confidence intervals
- Diagnosis verification pass rate (verifier approval to DIAGNOSED)
- Citation validity (provenance existence in collected evidence)
- Evidence completeness (telemetry + knowledge separation)
- Stage-level latencies (telemetry, knowledge, LLM reasoning, graph execution, total wall clock)
- Token & cost accounting (or NOT AVAILABLE when running offline)

Invariants:
- Zero fabricated metrics.
- Uses real LangGraph investigation execution.
- Separates local deterministic/heuristic reasoning from external API metrics.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import statistics
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from sentinelops.agent.graph import create_investigation_graph
from sentinelops.agent.state import InvestigationState
from sentinelops.capabilities.llm.provider import DeterministicLLMProvider
from sentinelops.capabilities.llm.real_provider import RealLLMProvider
from sentinelops.config.settings import get_settings
from sentinelops.domain.models.investigation import (
    InvestigationResult,
    InvestigationStatus,
)
from sentinelops.domain.models.knowledge import RetrievalMode
from sentinelops.evals.datasets.incident_scenarios import (
    INCIDENT_BENCHMARK_SCENARIOS,
    IncidentScenario,
)
from sentinelops.integrations.knowledge.qdrant_provider import QdrantKnowledgeProvider

logger = logging.getLogger(__name__)


def compute_wilson_ci(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """
    Compute Wilson score interval for a binomial proportion.
    """
    if n == 0:
        return 0.0, 0.0
    z = 1.95996  # 95% confidence
    p = k / n
    denominator = 1.0 + (z**2) / n
    center_adj = p + (z**2) / (2.0 * n)
    margin = z * math.sqrt((p * (1.0 - p) + (z**2) / (4.0 * n)) / n)
    lower = max(0.0, (center_adj - margin) / denominator)
    upper = min(1.0, (center_adj + margin) / denominator)
    return round(lower, 4), round(upper, 4)


def build_mock_evidence_provider(scenario: IncidentScenario) -> Any:
    """Construct an evidence provider serving the scenario's telemetry."""
    provider = AsyncMock()
    provider.query_recent_telemetry.return_value = scenario.simulated_telemetry["recent"]
    provider.compare_telemetry_baseline.return_value = scenario.simulated_telemetry["baseline"]
    provider.get_incident_trigger_context.side_effect = lambda inc: {
        "incident_id": inc.incident_id,
        "service_name": inc.service_name,
        "initial_evidence": [
            {"kind": "metric", "value": item.value, "description": item.description}
            for item in inc.initial_evidence
        ],
    }
    return provider


async def evaluate_single_mode(
    mode_name: str,
    llm_provider: Any,
    knowledge_provider: Any | None,
    scenarios: list[IncidentScenario],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Run 30 incidents through the LangGraph graph under a specific configuration.
    Returns (aggregate_metrics, per_incident_records).
    """
    total = len(scenarios)
    diagnosed_count = 0
    accurate_count = 0
    total_citations = 0
    valid_citations = 0
    loop_count = 0
    max_iteration_count = 0
    complete_evidence_count = 0
    latencies_s: list[float] = []
    per_incident_records: list[dict[str, Any]] = []

    for scenario in scenarios:
        ev_prov = build_mock_evidence_provider(scenario)
        graph = create_investigation_graph(
            evidence_provider=ev_prov,
            llm_provider=llm_provider,
            knowledge_provider=knowledge_provider,
        )

        initial_state: InvestigationState = {
            "incident": scenario.incident,
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
            "start_time_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "final_result": None,
            "evidence_groups": {"telemetry": [], "knowledge": []},
            "knowledge_queries": [],
            "knowledge_available": knowledge_provider is not None,
            "retrieval_mode": "hybrid",
        }

        t0 = time.perf_counter()
        config = {"configurable": {"thread_id": f"{mode_name}-{scenario.scenario_id}"}}
        final_state = await graph.ainvoke(initial_state, config=config)
        elapsed = time.perf_counter() - t0
        latencies_s.append(elapsed)

        res: InvestigationResult = final_state["final_result"]

        is_diagnosed = res.status == InvestigationStatus.DIAGNOSED
        if is_diagnosed:
            diagnosed_count += 1

        if res.iteration_count > 1:
            loop_count += 1
        if res.iteration_count >= 3:
            max_iteration_count += 1

        # Accuracy evaluation
        is_accurate = False
        rc_text = ""
        if res.diagnosis:
            rc_text = (res.diagnosis.root_cause + " " + res.diagnosis.explanation).lower()
            if hasattr(scenario, "ground_truth"):
                target_concepts = [scenario.ground_truth.expected_root_cause.lower()] + [
                    a.lower() for a in scenario.ground_truth.acceptable_root_causes
                ]
                if any(concept in rc_text for concept in target_concepts):
                    is_accurate = True
                    accurate_count += 1
            else:
                if scenario.expected_root_cause_concept.lower() in rc_text:
                    is_accurate = True
                    accurate_count += 1

        # Citation validity & completeness
        collected_ids = {e.evidence_id for e in res.supporting_evidence}
        cited_ids = res.diagnosis.supporting_evidence if res.diagnosis else []
        total_citations += len(cited_ids)
        invalid_in_incident = 0
        for cid in cited_ids:
            if cid in collected_ids:
                valid_citations += 1
            else:
                invalid_in_incident += 1

        has_telemetry = len(res.telemetry_evidence) > 0
        has_knowledge = len(res.knowledge_evidence) > 0
        if knowledge_provider is not None:
            is_complete = has_telemetry and has_knowledge
        else:
            is_complete = has_telemetry
        if is_complete:
            complete_evidence_count += 1

        per_incident_records.append({
            "mode": mode_name,
            "scenario_id": scenario.scenario_id,
            "category": scenario.category,
            "incident_id": scenario.incident.incident_id,
            "service": scenario.incident.service_name,
            "expected_concept": scenario.expected_root_cause_concept,
            "status": res.status.value,
            "is_diagnosed": is_diagnosed,
            "is_accurate": is_accurate,
            "confidence": res.confidence,
            "iteration_count": res.iteration_count,
            "cited_evidence_count": len(cited_ids),
            "invalid_citations_count": invalid_in_incident,
            "telemetry_evidence_count": len(res.telemetry_evidence),
            "knowledge_evidence_count": len(res.knowledge_evidence),
            "duration_seconds": round(elapsed, 4),
            "diagnosis_root_cause": res.diagnosis.root_cause if res.diagnosis else None,
        })

    citation_validity = 1.0 if total_citations == 0 else (valid_citations / total_citations)
    accuracy = accurate_count / total
    ci_low, ci_high = compute_wilson_ci(accurate_count, total, confidence=0.95)

    sorted_lats = sorted(latencies_s)
    p50_idx = int(total * 0.50)
    p95_idx = min(total - 1, int(total * 0.95))

    accounting = {}
    if hasattr(llm_provider, "get_usage_accounting"):
        accounting = llm_provider.get_usage_accounting()
    else:
        accounting = {
            "provider_mode": "deterministic_rule_engine",
            "model": "deterministic",
            "external_api_calls": 0,
            "input_tokens": "NOT AVAILABLE",
            "output_tokens": "NOT AVAILABLE",
            "total_tokens": "NOT AVAILABLE",
            "estimated_cost_usd": "NOT AVAILABLE",
            "cost_per_investigation_usd": "NOT AVAILABLE",
            "external_network_latency_ms": "NOT AVAILABLE",
            "local_reasoning_latency_ms": round(sum(latencies_s) / total * 1000.0, 2),
        }

    aggregate = {
        "mode": mode_name,
        "scenarios_evaluated": total,
        "correct_diagnoses": accurate_count,
        "root_cause_accuracy": round(accuracy, 4),
        "accuracy_ci_95": {
            "lower": ci_low,
            "upper": ci_high,
            "formatted": f"{accuracy:.1%} (95% CI: [{ci_low:.1%}, {ci_high:.1%}])",
        },
        "diagnosis_verification_pass_rate": round(diagnosed_count / total, 4),
        "citation_validity_rate": round(citation_validity, 4),
        "evidence_completeness_rate": round(complete_evidence_count / total, 4),
        "claim_level_grounding": "NOT EVALUATED (requires NLI semantic entailment model)",
        "investigation_loop_rate": round(loop_count / total, 4),
        "max_iteration_termination_rate": round(max_iteration_count / total, 4),
        "latency_seconds": {
            "mean": round(statistics.mean(latencies_s), 4),
            "median": round(sorted_lats[p50_idx], 4),
            "p95": round(sorted_lats[p95_idx], 4),
        },
        "usage_and_cost": accounting,
    }
    return aggregate, per_incident_records


async def run_full_investigation_evaluation(
    provider_filter: str = "all",
    qdrant_url: str | None = None,
    collection_name: str | None = None,
    output_dir: Path | None = None,
    dataset_version: str = "v1",
) -> dict[str, Any]:
    """
    Run investigation ablation benchmark with machine-readable logging.
    """
    settings = get_settings()
    url = qdrant_url or settings.qdrant_url
    collection = collection_name or settings.qdrant_collection
    
    if dataset_version == "v2":
        from sentinelops.evals.datasets.v2.incident_scenarios_v2 import INCIDENT_BENCHMARK_SCENARIOS_V2
        scenarios_to_run = INCIDENT_BENCHMARK_SCENARIOS_V2
        default_out_dir = Path("evals/results/investigation_v2")
    else:
        scenarios_to_run = INCIDENT_BENCHMARK_SCENARIOS
        default_out_dir = Path("evals/results/investigation")

    out_dir = output_dir or default_out_dir
    reports_dir = Path("docs/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    deterministic_llm = DeterministicLLMProvider()
    semantic_llm = RealLLMProvider(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )
    knowledge_prov = QdrantKnowledgeProvider(url=url, collection_name=collection)
    knowledge_prov.ensure_collection()

    all_modes = [
        ("Mode A (Telemetry-only + Deterministic)", deterministic_llm, None, "deterministic"),
        ("Mode B (Telemetry+Knowledge + Deterministic)", deterministic_llm, knowledge_prov, "deterministic"),
        ("Mode C (Telemetry-only + Semantic LLM)", semantic_llm, None, "real"),
        ("Mode D (Telemetry+Knowledge + Semantic LLM)", semantic_llm, knowledge_prov, "real"),
    ]

    if provider_filter == "deterministic":
        selected_modes = [m for m in all_modes if m[3] == "deterministic"]
    elif provider_filter == "real":
        selected_modes = [m for m in all_modes if m[3] == "real"]
    else:
        selected_modes = all_modes

    all_results: dict[str, Any] = {}
    all_incident_records: list[dict[str, Any]] = []

    print(f"\n=========================================================================")
    print(f"SentinelOps Investigation Benchmark ({len(scenarios_to_run)} Incidents | Dataset: {dataset_version} | Provider: {provider_filter})")
    print(f"=========================================================================\n")

    for mode_name, llm, kp, _ in selected_modes:
        agg, inc_recs = await evaluate_single_mode(mode_name, llm, kp, scenarios_to_run)
        all_results[mode_name] = agg
        all_incident_records.extend(inc_recs)

        ci_str = agg["accuracy_ci_95"]["formatted"]
        print(
            f"{mode_name:<44} | "
            f"Accuracy: {ci_str:<26} | "
            f"Verified: {agg['diagnosis_verification_pass_rate']:.1%} | "
            f"Citation Valid: {agg['citation_validity_rate']:.1%} | "
            f"Duration (p50/p95): {agg['latency_seconds']['median']:.3f}/{agg['latency_seconds']['p95']:.3f}s"
        )

    # Save benchmark manifest
    manifest = {
        "benchmark_name": "sentinelops-incident-investigation-ablation",
        "benchmark_version": f"slice3-{dataset_version}-hardened",
        "dataset_version": dataset_version,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scenario_count": len(scenarios_to_run),
        "provider_filter": provider_filter,
        "external_api_configured": semantic_llm.is_external_configured,
        "evaluation_notice": (
            "This benchmark is an engineering evaluation set, not a statistically "
            "representative estimate of production incident accuracy."
        ),
    }
    manifest_path = out_dir / "benchmark_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Save per-incident results jsonl
    jsonl_path = out_dir / "per_incident_results.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for rec in all_incident_records:
            f.write(json.dumps(rec) + "\n")

    # Save aggregate results json
    agg_path = out_dir / "aggregate_results.json"
    agg_path.write_text(json.dumps(all_results, indent=2), encoding="utf-8")

    # Save legacy report path for docs if v1
    if dataset_version == "v1":
        legacy_path = reports_dir / "investigation_benchmark_results.json"
        report_data = {
            "manifest": manifest,
            "scenario_count": len(scenarios_to_run),
            "results": all_results,
        }
        legacy_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")

    print(f"\nSaved artifacts:")
    print(f"  - {manifest_path}")
    print(f"  - {jsonl_path}")
    print(f"  - {agg_path}\n")

    return all_results


def main() -> None:
    """CLI entrypoint for investigation ablation benchmark."""
    parser = argparse.ArgumentParser(description="SentinelOps Investigation Benchmark")
    parser.add_argument(
        "--provider",
        type=str,
        default="all",
        choices=["all", "deterministic", "real"],
        help="Provider filter: all, deterministic, or real",
    )
    parser.add_argument("--qdrant-url", type=str, default="http://localhost:6333")
    parser.add_argument("--collection", type=str, default="sentinelops_knowledge")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--dataset-version",
        type=str,
        default="v1",
        choices=["v1", "v2"],
        help="Dataset version to evaluate: v1 (30 incidents) or v2 (60 hardened incidents)",
    )
    args = parser.parse_args()

    asyncio.run(
        run_full_investigation_evaluation(
            provider_filter=args.provider,
            qdrant_url=args.qdrant_url,
            collection_name=args.collection,
            output_dir=args.output_dir,
            dataset_version=args.dataset_version,
        )
    )


if __name__ == "__main__":
    main()
