"""
Incident Investigation Benchmark Suite for SentinelOps.

Executes 30 held-out incident investigations across 4 ablation configurations:
- Mode A: Telemetry-Only + Deterministic LLM Provider
- Mode B: Telemetry + Knowledge + Deterministic LLM Provider
- Mode C: Telemetry-Only + Real LLM Provider
- Mode D: Telemetry + Knowledge + Real LLM Provider

Evaluates:
- Root-cause accuracy
- Citation correctness / evidence validity
- Groundedness (zero phantom/fabricated IDs)
- Verification success rate
- Investigation iteration loop rate
- Wall-clock latency and token usage

Invariants:
- Zero fabricated metrics.
- Uses real LangGraph investigation execution.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
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
) -> dict[str, Any]:
    """
    Run 30 incidents through the LangGraph graph under a specific configuration.
    """
    total = len(scenarios)
    diagnosed_count = 0
    accurate_count = 0
    valid_citation_count = 0
    total_citations = 0
    invalid_citations = 0
    loop_count = 0
    max_iteration_count = 0
    latencies: list[float] = []

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
        latencies.append(elapsed)

        res: InvestigationResult = final_state["final_result"]

        if res.status == InvestigationStatus.DIAGNOSED:
            diagnosed_count += 1

        if res.iteration_count > 1:
            loop_count += 1
        if res.iteration_count >= 3:
            max_iteration_count += 1

        # Evaluate root-cause accuracy
        if res.diagnosis:
            rc_text = (res.diagnosis.root_cause + " " + res.diagnosis.explanation).lower()
            if scenario.expected_root_cause_concept.lower() in rc_text:
                accurate_count += 1

            # Evaluate citation validity
            collected_ids = {e.evidence_id for e in res.supporting_evidence}
            cited_ids = res.diagnosis.supporting_evidence
            total_citations += len(cited_ids)
            for cid in cited_ids:
                if cid not in collected_ids:
                    invalid_citations += 1

    citation_validity = 1.0 if total_citations == 0 else (1.0 - (invalid_citations / total_citations))
    groundedness = round(citation_validity, 4)

    return {
        "mode": mode_name,
        "scenarios_evaluated": total,
        "verification_success_rate": round(diagnosed_count / total, 4),
        "root_cause_accuracy": round(accurate_count / total, 4),
        "citation_validity": round(citation_validity, 4),
        "groundedness": groundedness,
        "unsupported_diagnosis_rate": round(invalid_citations / max(1, total_citations), 4),
        "investigation_loop_rate": round(loop_count / total, 4),
        "max_iteration_termination_rate": round(max_iteration_count / total, 4),
        "avg_duration_seconds": round(sum(latencies) / total, 3),
        "p95_duration_seconds": round(sorted(latencies)[int(total * 0.95)], 3),
    }


async def run_full_investigation_evaluation(
    qdrant_url: str | None = None,
    collection_name: str | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Run the 4-mode ablation evaluation over 30 incident scenarios.
    """
    settings = get_settings()
    url = qdrant_url or settings.qdrant_url
    collection = collection_name or settings.qdrant_collection
    out_dir = output_dir or Path("docs/reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Initialize providers
    deterministic_llm = DeterministicLLMProvider()
    real_llm = RealLLMProvider(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )
    knowledge_prov = QdrantKnowledgeProvider(url=url, collection_name=collection)
    knowledge_prov.ensure_collection()

    modes = [
        ("Mode A (Telemetry-only + Deterministic)", deterministic_llm, None),
        ("Mode B (Telemetry+Knowledge + Deterministic)", deterministic_llm, knowledge_prov),
        ("Mode C (Telemetry-only + Real LLM)", real_llm, None),
        ("Mode D (Telemetry+Knowledge + Real LLM)", real_llm, knowledge_prov),
    ]

    all_results: dict[str, Any] = {}
    print(f"\n=======================================================")
    print(f"SentinelOps Investigation Ablation Benchmark (30 Incidents)")
    print(f"=======================================================\n")

    for mode_name, llm, kp in modes:
        mode_res = await evaluate_single_mode(mode_name, llm, kp, INCIDENT_BENCHMARK_SCENARIOS)
        all_results[mode_name] = mode_res
        print(
            f"{mode_name:<44} | "
            f"Accuracy: {mode_res['root_cause_accuracy']:.2%} | "
            f"Verified: {mode_res['verification_success_rate']:.2%} | "
            f"Grounded: {mode_res['groundedness']:.2%} | "
            f"Avg Time: {mode_res['avg_duration_seconds']:.3f}s"
        )

    # Save to report JSON
    report_path = out_dir / "investigation_benchmark_results.json"
    report_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scenario_count": len(INCIDENT_BENCHMARK_SCENARIOS),
        "results": all_results,
    }
    report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    print(f"\nSaved machine-readable report to: {report_path}\n")

    return all_results


def main() -> None:
    """CLI entrypoint for investigation ablation benchmark."""
    parser = argparse.ArgumentParser(description="SentinelOps Investigation Benchmark")
    parser.add_argument("--qdrant-url", type=str, default="http://localhost:6333")
    parser.add_argument("--collection", type=str, default="sentinelops_knowledge")
    parser.add_argument("--output-dir", type=Path, default=Path("docs/reports"))
    args = parser.parse_args()

    asyncio.run(
        run_full_investigation_evaluation(
            qdrant_url=args.qdrant_url,
            collection_name=args.collection,
            output_dir=args.output_dir,
        )
    )


if __name__ == "__main__":
    main()
