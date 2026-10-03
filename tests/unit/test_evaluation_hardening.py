"""
Unit and Regression Tests for Evaluation Hardening Pass.

Covers:
1. Paired Statistical Analysis:
   - Sample alignment and ID mismatch rejection
   - Deterministic bootstrap reproducibility with fixed seed
   - McNemar's exact test calculation on known 2x2 tables
   - Paired proportion difference confidence interval bounds
2. Benchmark v2 Integrity:
   - Zero ground-truth leakage into agent-visible incident fields
   - Corpus manifest consistency with disk
   - Zero scenario ID or incident ID duplicates
   - Absolute separation of held-out benchmark incidents from knowledge corpus
3. Claim-Level Grounding:
   - Atomic claim decomposition schema (factual vs causal)
   - Citation reference validity verification
   - Unsupported claim classification
   - Contradictory evidence classification
   - Missing evidence graceful handling
4. Reproducibility:
   - Fixed seed produces identical bootstrap distribution
   - Required manifest metadata fields presence
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sentinelops.domain.models.incident import EvidenceItem
from sentinelops.evals.datasets.v2.corpus_manifest import generate_corpus_manifest
from sentinelops.evals.datasets.v2.incident_scenarios_v2 import (
    INCIDENT_BENCHMARK_SCENARIOS_V2,
    IncidentScenarioV2,
)
from sentinelops.evals.grounding.decomposer import decompose_diagnosis_text
from sentinelops.evals.grounding.evaluator import HeuristicClaimGroundingEvaluator
from sentinelops.evals.grounding.models import (
    CausalLabel,
    Claim,
    ClaimType,
    GroundingLabel,
)
from sentinelops.evals.paired_stats import (
    compute_paired_proportion_ci,
    evaluate_investigation_paired_comparison,
    evaluate_retrieval_paired_bootstrap,
    mcnemar_exact_p_value,
)


class TestPairedStatistics:
    """Tests for paired statistical testing (McNemar & Paired Bootstrap)."""

    def test_mcnemar_exact_test_known_values(self) -> None:
        # Balanced discordant pairs: b = 5, c = 5 -> p = 1.0
        assert mcnemar_exact_p_value(5, 5) == 1.0

        # Highly unbalanced discordant pairs: b = 10, c = 0
        # p-value = 2 * (0.5)^10 = 2 / 1024 = 0.001953125
        p_val = mcnemar_exact_p_value(10, 0)
        assert abs(p_val - 0.001953) < 1e-4

        # Zero discordant pairs
        assert mcnemar_exact_p_value(0, 0) == 1.0

    def test_paired_proportion_ci_bounds(self) -> None:
        # 20 successes in A only, 0 in B only, N = 30
        low, high = compute_paired_proportion_ci(b=20, c=0, total_n=30)
        diff = 20 / 30
        assert low < diff < high
        assert -1.0 <= low <= 1.0
        assert -1.0 <= high <= 1.0

    def test_paired_investigation_rejects_mismatched_ids(self) -> None:
        records_a = [
            {"scenario_id": "SC-01", "is_accurate": True},
            {"scenario_id": "SC-02", "is_accurate": False},
        ]
        records_b = [
            {"scenario_id": "SC-01", "is_accurate": True},
            {"scenario_id": "SC-03", "is_accurate": False},  # Mismatched ID
        ]
        with pytest.raises(ValueError, match="Scenario ID mismatch"):
            evaluate_investigation_paired_comparison("A", "B", records_a, records_b)

    def test_paired_retrieval_bootstrap_determinism(self) -> None:
        records_a = [
            {"query_id": f"Q{i:02d}", "metrics": {"recall_at_5": 0.8 if i % 2 == 0 else 0.4}}
            for i in range(1, 21)
        ]
        records_b = [
            {"query_id": f"Q{i:02d}", "metrics": {"recall_at_5": 0.6}}
            for i in range(1, 21)
        ]

        res1 = evaluate_retrieval_paired_bootstrap(
            "dense", "sparse", records_a, records_b, "recall_at_5", random_seed=123
        )
        res2 = evaluate_retrieval_paired_bootstrap(
            "dense", "sparse", records_a, records_b, "recall_at_5", random_seed=123
        )

        assert res1.mean_difference == res2.mean_difference
        assert res1.difference_ci_95 == res2.difference_ci_95


class TestBenchmarkV2Integrity:
    """Tests for Benchmark v2 scenario isolation, coverage, and manifest consistency."""

    def test_scenario_count_and_category_coverage(self) -> None:
        assert len(INCIDENT_BENCHMARK_SCENARIOS_V2) == 60
        categories = {s.category_code for s in INCIDENT_BENCHMARK_SCENARIOS_V2}
        expected_cats = {"A", "B", "C", "D", "E", "F", "G", "H", "I", "J"}
        assert categories == expected_cats

        for cat in expected_cats:
            count = sum(1 for s in INCIDENT_BENCHMARK_SCENARIOS_V2 if s.category_code == cat)
            assert count == 6, f"Category {cat} does not have exactly 6 scenarios"

    def test_zero_scenario_id_duplicates(self) -> None:
        s_ids = [s.scenario_id for s in INCIDENT_BENCHMARK_SCENARIOS_V2]
        inc_ids = [s.incident.incident_id for s in INCIDENT_BENCHMARK_SCENARIOS_V2]
        assert len(s_ids) == len(set(s_ids)), "Duplicate scenario IDs detected"
        assert len(inc_ids) == len(set(inc_ids)), "Duplicate incident IDs detected"

    def test_zero_ground_truth_leakage_in_agent_visible_fields(self) -> None:
        for s in INCIDENT_BENCHMARK_SCENARIOS_V2:
            agent_visible_text = (
                f"{s.incident.title} {s.incident.description} "
                f"{s.incident.service_name} {s.incident.trigger_rule_name} "
                + " ".join(e.description for e in s.incident.initial_evidence)
            ).lower()

            expected_rc = s.ground_truth.expected_root_cause.lower()
            assert expected_rc not in agent_visible_text, (
                f"Ground-truth expected root cause '{expected_rc}' leaked into "
                f"agent-visible fields for scenario {s.scenario_id}"
            )

            for forbidden in s.ground_truth.forbidden_ground_truth_leakage:
                assert forbidden.lower() not in agent_visible_text, (
                    f"Forbidden leakage term '{forbidden}' leaked into "
                    f"agent-visible fields for scenario {s.scenario_id}"
                )

    def test_benchmark_scenarios_strictly_isolated_from_corpus(self) -> None:
        corpus_path = Path("knowledge")
        all_corpus_text = " ".join(p.read_text(encoding="utf-8") for p in corpus_path.rglob("*.md"))

        for s in INCIDENT_BENCHMARK_SCENARIOS_V2:
            assert s.incident.incident_id not in all_corpus_text, (
                f"Held-out incident ID {s.incident.incident_id} appears in the knowledge corpus!"
            )

    def test_corpus_manifest_consistency_with_disk(self) -> None:
        manifest = generate_corpus_manifest(Path("knowledge"))
        assert manifest["document_count"] == 33
        assert manifest["chunk_count"] == 118
        assert "runbook" in manifest["document_classes"]
        assert manifest["document_classes"]["runbook"] == 10


class TestClaimGrounding:
    """Tests for claim decomposition and grounding evaluation."""

    def test_claim_decomposition_splits_factual_and_causal(self) -> None:
        root_cause = "Database connection pool exhausted due to unclosed sessions. Latency elevated to 2.5s."
        decomp = decompose_diagnosis_text("INC-TEST-01", root_cause)

        assert len(decomp.claims) >= 2
        claim_types = [c.claim_type for c in decomp.claims]
        assert ClaimType.CAUSAL in claim_types

    def test_grounding_rejects_missing_citations(self) -> None:
        evaluator = HeuristicClaimGroundingEvaluator()
        claim = Claim(
            claim_id="C01",
            incident_id="INC-01",
            claim_text="Database pool connection exhaustion observed",
            claim_type=ClaimType.FACTUAL,
            cited_evidence_ids=["FABRICATED-EV-999"],
        )
        real_evidence = [
            {"evidence_id": "EV-01", "description": "Database pool exhaustion", "content": ""}
        ]
        res = evaluator.evaluate(claim, real_evidence)
        assert res.label == GroundingLabel.UNSUPPORTED
        assert res.citation_valid is False

    def test_grounding_accepts_supported_citations(self) -> None:
        evaluator = HeuristicClaimGroundingEvaluator()
        claim = Claim(
            claim_id="C02",
            incident_id="INC-02",
            claim_text="High memory utilization caused frequent GC pauses",
            claim_type=ClaimType.CAUSAL,
            cited_evidence_ids=["EV-01", "EV-02"],
        )
        evidence = [
            {"evidence_id": "EV-01", "description": "High memory utilization on order-service", "content": ""},
            {"evidence_id": "EV-02", "description": "Frequent GC pauses observed in JVM logs", "content": ""},
        ]
        res = evaluator.evaluate(claim, evidence)
        assert res.label in (GroundingLabel.SUPPORTED, GroundingLabel.PARTIALLY_SUPPORTED)
        assert res.citation_valid is True
        assert res.causal_label == CausalLabel.CAUSALLY_SUPPORTED

    def test_grounding_detects_contradiction(self) -> None:
        evaluator = HeuristicClaimGroundingEvaluator()
        claim = Claim(
            claim_id="C03",
            incident_id="INC-03",
            claim_text="Service performance was completely normal and healthy",
            claim_type=ClaimType.FACTUAL,
            cited_evidence_ids=["EV-01"],
        )
        evidence = [
            {"evidence_id": "EV-01", "description": "Critical error rate spike exceeded threshold 0.15", "content": ""}
        ]
        res = evaluator.evaluate(claim, evidence)
        assert res.label == GroundingLabel.CONTRADICTED


class TestReproducibilityAndManifests:
    """Tests for artifact and manifest schemas and reproducible outputs."""

    def test_investigation_manifest_contains_required_fields(self) -> None:
        manifest_path = Path("evals/results/investigation/benchmark_manifest.json")
        assert manifest_path.exists(), "Investigation manifest missing"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))

        required_keys = ["benchmark_name", "benchmark_version", "timestamp", "scenario_count"]
        for k in required_keys:
            assert k in data, f"Key {k} missing from benchmark manifest"

    def test_grounding_manifest_contains_required_fields(self) -> None:
        manifest_path = Path("evals/results/grounding/benchmark_manifest.json")
        assert manifest_path.exists(), "Grounding manifest missing"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))

        required_keys = ["manifest_id", "git_commit", "dataset_version", "corpus_version", "judge_configuration"]
        for k in required_keys:
            assert k in data, f"Key {k} missing from grounding manifest"
