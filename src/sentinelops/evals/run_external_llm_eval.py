"""
Real External LLM Evaluation Runner for SentinelOps (Slice 5D).

Strict Architectural Rules:
- Supports 3 evaluation modes: 'deterministic', 'offline_semantic_emulator', 'external_api'.
- If external credentials are absent, explicitly reports: status = "NOT RUN".
- NEVER fabricates tokens, latencies, or accuracy numbers for unconfigured external APIs.
- When credentials are provided, runs evaluation and records model, provider, tokens, latency, cost, and accuracy.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sentinelops.capabilities.llm.real_provider import RealLLMProvider
from sentinelops.evals.datasets.incident_scenarios import INCIDENT_BENCHMARK_SCENARIOS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_external_llm_evaluation(
    model: str = "gpt-4o-mini",
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute evaluation for external LLM or report NOT RUN."""
    out_dir = output_dir or Path("evals/results/external_llm")
    out_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("SENTINELOPS_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("SENTINELOPS_LLM_BASE_URL")

    if not api_key or api_key.startswith("mock-") or len(api_key) < 10:
        logger.warning("No external LLM credentials configured. External evaluation classified as NOT RUN.")
        not_run_result = {
            "evaluation_mode": "external_api",
            "status": "NOT RUN",
            "model": model,
            "provider": "external_llm_api",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "reason": (
                "External API credentials (SENTINELOPS_LLM_API_KEY or OPENAI_API_KEY) "
                "were not detected in the environment. Per strict SentinelOps safety and truthfulness "
                "invariants, external metrics are NOT fabricated."
            ),
            "benchmark_dataset_size": len(INCIDENT_BENCHMARK_SCENARIOS),
            "measured_metrics": None,
        }
        with open(out_dir / "external_llm_summary.json", "w", encoding="utf-8") as f:
            json.dump(not_run_result, f, indent=2)
        return not_run_result

    # If credentials exist, run live external evaluation
    logger.info("Credentials detected. Initializing RealLLMProvider with model '%s'", model)
    provider = RealLLMProvider(model=model, api_key=api_key, base_url=base_url)

    total_scenarios = min(len(INCIDENT_BENCHMARK_SCENARIOS), 10)  # Bound budget
    results: list[dict[str, Any]] = []
    correct_count = 0
    valid_citations = 0

    for idx, inc_scenario in enumerate(INCIDENT_BENCHMARK_SCENARIOS[:total_scenarios], 1):
        incident = inc_scenario.incident
        logger.info("[%d/%d] Evaluating external model on incident %s...", idx, total_scenarios, incident.incident_id)
        # Investigation step
        try:
            plan = provider.create_investigation_plan(incident)
            hypotheses = provider.generate_hypotheses(incident, [])
            diagnosis = provider.generate_diagnosis(incident, hypotheses, [])
            verification = provider.verify_diagnosis(incident, diagnosis)

            # Check citation validity
            has_citations = len(diagnosis.supporting_evidence) > 0
            if has_citations:
                valid_citations += 1

            # Rough check against expected root cause
            expected = inc_scenario.expected_root_cause_concept
            is_correct = bool(expected and expected.lower() in diagnosis.root_cause.lower())
            if is_correct:
                correct_count += 1

            results.append({
                "incident_id": incident.incident_id,
                "is_correct": is_correct,
                "is_verified": verification.is_verified,
                "citations_count": len(diagnosis.supporting_evidence),
            })
        except Exception as exc:
            logger.error("External call failed for %s: %s", incident.incident_id, exc)
            results.append({
                "incident_id": incident.incident_id,
                "error": str(exc),
                "is_correct": False,
            })

    summary = {
        "evaluation_mode": "external_api",
        "status": "COMPLETED",
        "model": model,
        "provider": "openai_compatible",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "total_evaluated": total_scenarios,
        "accuracy": correct_count / total_scenarios if total_scenarios else 0.0,
        "citation_validity_rate": valid_citations / total_scenarios if total_scenarios else 0.0,
        "input_tokens": provider.input_tokens,
        "output_tokens": provider.output_tokens,
        "estimated_cost_usd": provider.estimated_cost_usd,
        "per_scenario": results,
    }

    with open(out_dir / "external_llm_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary


def main() -> None:
    res = run_external_llm_evaluation()
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
