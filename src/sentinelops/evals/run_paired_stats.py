"""
Paired Statistical Analysis Pipeline for SentinelOps Benchmarks.

Reads:
- evals/results/investigation/per_incident_results.jsonl
- evals/results/retrieval/per_query_results.jsonl

Computes:
1. Investigation paired comparisons:
   - Mode B vs Mode A (Telemetry+Knowledge+Det vs Telemetry+Det)
   - Mode D vs Mode C (Telemetry+Knowledge+Emulator vs Telemetry+Emulator)
   - Mode B vs Mode D (Telemetry+Knowledge+Det vs Telemetry+Knowledge+Emulator)
2. Retrieval query-level paired comparisons:
   - dense_only vs sparse_only
   - dense_only vs hybrid
   - hybrid vs hybrid_plus_rerank
   for Recall@5, Recall@10, MRR, nDCG@10.

Writes:
- evals/results/statistics/investigation_pairwise.json
- evals/results/statistics/retrieval_pairwise.json
"""
from __future__ import annotations

import argparse
import json
import logging
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sentinelops.evals.paired_stats import (
    evaluate_investigation_paired_comparison,
    evaluate_retrieval_paired_bootstrap,
)

logger = logging.getLogger(__name__)


def get_git_commit_hash() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "UNKNOWN"


def run_investigation_paired_analysis(
    input_file: Path,
    output_file: Path,
    benchmark_manifest_id: str = "inv-bench-20261003",
    dataset_version: str = "v1",
) -> dict[str, Any]:
    """Execute paired McNemar comparisons across investigation modes."""
    logger.info("Reading investigation records from: %s", input_file)
    records_by_mode: dict[str, list[dict[str, Any]]] = {}

    with open(input_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            mode = item["mode"]
            records_by_mode.setdefault(mode, []).append(item)

    # Support both full names and prefix matches
    def find_mode_key(target_prefix: str) -> str | None:
        for k in records_by_mode:
            if k.startswith(target_prefix):
                return k
        return None

    pairs_to_test = [
        ("Mode B", "Mode A"),
        ("Mode D", "Mode C"),
        ("Mode B", "Mode D"),
    ]

    comparisons: list[dict[str, Any]] = []

    for prefix_a, prefix_b in pairs_to_test:
        mode_a = find_mode_key(prefix_a)
        mode_b = find_mode_key(prefix_b)
        if not mode_a or not mode_b:
            logger.warning("Skipping pair (%s, %s) - mode missing in data", prefix_a, prefix_b)
            continue

        res = evaluate_investigation_paired_comparison(
            mode_a_name=mode_a,
            mode_b_name=mode_b,
            records_a=records_by_mode[mode_a],
            records_b=records_by_mode[mode_b],
        )
        res_dict = res.to_dict()
        res_dict.update({
            "benchmark_manifest_id": benchmark_manifest_id,
            "dataset_version": dataset_version,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        })
        comparisons.append(res_dict)

    output = {
        "metadata": {
            "analysis_type": "investigation_paired_analysis",
            "git_commit": get_git_commit_hash(),
            "dataset_version": dataset_version,
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "statistical_methods": [
                "McNemar's Exact Test (Binomial distribution on discordant pairs)",
                "Wald Paired Proportion Difference 95% Confidence Interval",
            ],
        },
        "comparisons": comparisons,
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    logger.info("Saved investigation pairwise analysis to: %s", output_file)
    return output


def run_retrieval_paired_analysis(
    input_file: Path,
    output_file: Path,
    benchmark_manifest_id: str = "ret-bench-20261003",
    dataset_version: str = "v1",
    bootstrap_iterations: int = 2000,
    random_seed: int = 42,
) -> dict[str, Any]:
    """Execute paired bootstrap comparisons across retrieval modes."""
    logger.info("Reading retrieval records from: %s", input_file)
    records_by_mode: dict[str, list[dict[str, Any]]] = {}

    with open(input_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            mode = item["mode"]
            records_by_mode.setdefault(mode, []).append(item)

    pairs_to_test = [
        ("dense_only", "sparse_only"),
        ("dense_only", "hybrid"),
        ("hybrid", "hybrid_plus_rerank"),
    ]
    metrics = ["recall_at_5", "recall_at_10", "reciprocal_rank", "ndcg_at_10"]

    comparisons: list[dict[str, Any]] = []

    for mode_a, mode_b in pairs_to_test:
        if mode_a not in records_by_mode or mode_b not in records_by_mode:
            logger.warning("Skipping pair (%s, %s) - mode missing in data", mode_a, mode_b)
            continue

        for metric in metrics:
            res = evaluate_retrieval_paired_bootstrap(
                mode_a_name=mode_a,
                mode_b_name=mode_b,
                records_a=records_by_mode[mode_a],
                records_b=records_by_mode[mode_b],
                metric_name=metric,
                bootstrap_iterations=bootstrap_iterations,
                random_seed=random_seed,
            )
            res_dict = res.to_dict()
            res_dict.update({
                "benchmark_manifest_id": benchmark_manifest_id,
                "dataset_version": dataset_version,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            })
            comparisons.append(res_dict)

    output = {
        "metadata": {
            "analysis_type": "retrieval_paired_bootstrap_analysis",
            "git_commit": get_git_commit_hash(),
            "dataset_version": dataset_version,
            "bootstrap_iterations": bootstrap_iterations,
            "random_seed": random_seed,
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "statistical_methods": [
                "Paired Percentile Bootstrap (resampled with replacement per query)",
                "Empirical 95% Bootstrap Confidence Interval",
            ],
        },
        "comparisons": comparisons,
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    logger.info("Saved retrieval pairwise analysis to: %s", output_file)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="SentinelOps Paired Statistical Analysis")
    parser.add_argument(
        "--investigation-input",
        type=Path,
        default=Path("evals/results/investigation/per_incident_results.jsonl"),
        help="Path to per-incident investigation JSONL results",
    )
    parser.add_argument(
        "--investigation-output",
        type=Path,
        default=Path("evals/results/statistics/investigation_pairwise.json"),
        help="Path for investigation pairwise output JSON",
    )
    parser.add_argument(
        "--retrieval-input",
        type=Path,
        default=Path("evals/results/retrieval/per_query_results.jsonl"),
        help="Path to per-query retrieval JSONL results",
    )
    parser.add_argument(
        "--retrieval-output",
        type=Path,
        default=Path("evals/results/statistics/retrieval_pairwise.json"),
        help="Path for retrieval pairwise output JSON",
    )
    parser.add_argument("--iterations", type=int, default=2000, help="Bootstrap iterations")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for bootstrap")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.investigation_input.exists():
        run_investigation_paired_analysis(args.investigation_input, args.investigation_output)
    else:
        logger.warning("Investigation input file does not exist: %s", args.investigation_input)

    if args.retrieval_input.exists():
        run_retrieval_paired_analysis(
            args.retrieval_input,
            args.retrieval_output,
            bootstrap_iterations=args.iterations,
            random_seed=args.seed,
        )
    else:
        logger.warning("Retrieval input file does not exist: %s", args.retrieval_input)


if __name__ == "__main__":
    main()
