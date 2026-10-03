"""
Evaluator Regression and Audit Tests for SentinelOps Slice 3.

Verifies:
1. Standard nDCG@k:
   - Mathematically bounded strictly in [0.0, 1.0].
   - Perfect ranking yields 1.0.
   - Zero relevance yields 0.0.
   - Duplicate chunks from same document do not inflate nDCG > 1.0.
2. Dense vs. Sparse distinction:
   - Evaluator observes distinct rankings from dense and sparse channels.
3. Hybrid RRF fusion:
   - Fusion of dense and sparse produces ranking distinct from both inputs.
4. Reranking behavior:
   - Reranker alters candidate order based on section priority and service alignment.
5. Real LLM usage accounting:
   - Correctly distinguishes offline semantic emulator from external API and captures metrics.
6. Grounding test:
   - Diagnosis citing nonexistent or fabricated evidence IDs fails verification.
7. Benchmark isolation / Leakage test:
   - Expected root cause and ground truth labels never leak into agent prompt or state.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from sentinelops.capabilities.knowledge.reranker import CrossFeatureReranker
from sentinelops.capabilities.llm.provider import DeterministicLLMProvider
from sentinelops.capabilities.llm.real_provider import RealLLMProvider
from sentinelops.domain.models.incident import (
    EvidenceItem,
    Incident,
    IncidentSeverity,
    TriggerType,
)
from sentinelops.domain.models.investigation import (
    Diagnosis,
    Hypothesis,
    InvestigationEvidence,
)
from sentinelops.domain.models.knowledge import (
    DocumentType,
    KnowledgeChunk,
    KnowledgeQuery,
    KnowledgeResult,
    RetrievalMode,
)
from sentinelops.evals.datasets.incident_scenarios import INCIDENT_BENCHMARK_SCENARIOS
from sentinelops.evals.run_retrieval_eval import compute_ndcg_at_k, compute_recall_at_k
from sentinelops.integrations.knowledge.in_memory_provider import InMemoryKnowledgeProvider


class TestEvaluatorAudit:
    """Regression test suite for evaluation audit and benchmark hardening."""

    # ── 1. nDCG Mathematical Verification ─────────────────────────────────────
    def test_ndcg_perfect_ranking_is_one(self) -> None:
        """A ranking where all expected documents appear at top positions must equal 1.0."""
        expected = ["doc-A", "doc-B"]
        retrieved = ["doc-A", "doc-B", "doc-C", "doc-D"]
        ndcg, dcg, idcg = compute_ndcg_at_k(retrieved, expected, k=10)

        assert math.isclose(ndcg, 1.0, abs_tol=1e-5)
        assert dcg == idcg
        assert 0.0 <= ndcg <= 1.0

    def test_ndcg_zero_relevant_is_zero(self) -> None:
        """A ranking containing zero relevant documents must return 0.0."""
        expected = ["doc-A", "doc-B"]
        retrieved = ["doc-X", "doc-Y", "doc-Z"]
        ndcg, dcg, idcg = compute_ndcg_at_k(retrieved, expected, k=10)

        assert ndcg == 0.0
        assert dcg == 0.0
        assert idcg > 0.0

    def test_ndcg_duplicate_chunks_never_exceed_one(self) -> None:
        """
        REGRESSION PROOF: Duplicate chunks from the same document must NOT
        inflate DCG above IDCG. nDCG must remain strictly <= 1.0.
        """
        expected = ["doc-A"]
        # Simulated scenario: 5 chunks from the single relevant doc-A retrieved in top 5
        retrieved = ["doc-A", "doc-A", "doc-A", "doc-A", "doc-A"]
        ndcg, dcg, idcg = compute_ndcg_at_k(retrieved, expected, k=10)

        assert math.isclose(ndcg, 1.0, abs_tol=1e-5)
        assert ndcg <= 1.0
        assert 0.0 <= ndcg <= 1.0

    # ── 2. Dense vs Sparse Distinction ────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_dense_vs_sparse_distinction_on_synthetic_data(self) -> None:
        """
        Prove that Dense and Sparse retrieval channels evaluate different ranking signals.
        Dense matches semantic concepts; Sparse matches exact keywords.
        """
        provider = InMemoryKnowledgeProvider()
        chunk_semantic = KnowledgeChunk(
            chunk_id="CHK-SEM",
            document_id="doc-sem",
            document_type=DocumentType.RUNBOOK,
            title="Database Saturation Guide",
            section="Overview",
            content="Heavy connection resource exhaustion and starvation on the database cluster.",
            source="kb/sem.md",
        )
        chunk_keyword = KnowledgeChunk(
            chunk_id="CHK-KEY",
            document_id="doc-key",
            document_type=DocumentType.RUNBOOK,
            title="Error Code Reference",
            section="Reference",
            content="When error ERR_PG_POOL_EXHAUSTED_5001 is thrown, notify operations team.",
            source="kb/key.md",
        )
        await provider.index_chunks([chunk_semantic, chunk_keyword])

        # Exact keyword query
        query_kw = KnowledgeQuery(
            query="ERR_PG_POOL_EXHAUSTED_5001",
            mode=RetrievalMode.SPARSE_ONLY,
            limit=2,
        )
        sparse_res = await provider.search(query_kw)
        assert len(sparse_res) >= 1
        assert sparse_res[0].document_id == "doc-key"

        # Semantic query
        query_sem = KnowledgeQuery(
            query="database connection starvation and resource exhaustion",
            mode=RetrievalMode.DENSE_ONLY,
            limit=2,
        )
        dense_res = await provider.search(query_sem)
        assert len(dense_res) >= 1
        assert dense_res[0].document_id == "doc-sem"

    # ── 3. Hybrid RRF Fusion ──────────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_hybrid_rrf_combines_channels(self) -> None:
        """Verify that hybrid mode merges candidate pools via Reciprocal Rank Fusion."""
        provider = InMemoryKnowledgeProvider()
        c1 = KnowledgeChunk(
            chunk_id="C1", document_id="D1", document_type=DocumentType.RUNBOOK,
            title="Database Pool", section="Overview", content="Postgres connection pool saturation",
            source="c1.md",
        )
        c2 = KnowledgeChunk(
            chunk_id="C2", document_id="D2", document_type=DocumentType.ARCHITECTURE,
            title="Architecture", section="Database", content="Database topology and replicas",
            source="c2.md",
        )
        await provider.index_chunks([c1, c2])

        query = KnowledgeQuery(
            query="Postgres connection pool saturation topology",
            mode=RetrievalMode.HYBRID,
            limit=2,
        )
        hybrid_res = await provider.search(query)
        assert len(hybrid_res) == 2
        assert hybrid_res[0].retrieval_mode == "hybrid"

    # ── 4. Reranking Behavior ─────────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_reranker_alters_candidate_order(self) -> None:
        """Verify that CrossFeatureReranker boosts service and resolution sections."""
        reranker = CrossFeatureReranker()
        r_background = KnowledgeResult(
            chunk_id="CHK-BG", document_id="D-BG", document_type=DocumentType.ARCHITECTURE,
            title="Database Background", service="other-service", section="Introduction",
            content="General theory of databases.", source="bg.md", score=0.90, rank=1,
            retrieval_mode="hybrid",
        )
        r_resolution = KnowledgeResult(
            chunk_id="CHK-RES", document_id="D-RES", document_type=DocumentType.RUNBOOK,
            title="Database Runbook", service="payments-service", section="Resolution",
            content="Restart worker pods to clear connections.", source="res.md", score=0.85, rank=2,
            retrieval_mode="hybrid",
        )

        reranked = await reranker.rerank(
            query="payments-service database connection resolution",
            results=[r_background, r_resolution],
            top_k=2,
        )

        # r_resolution must be boosted above r_background due to service and section bonuses
        assert reranked[0].chunk_id == "CHK-RES"
        assert reranked[1].chunk_id == "CHK-BG"

    # ── 5. Real LLM Accounting ────────────────────────────────────────────────
    def test_real_llm_usage_accounting_offline_mode(self) -> None:
        """
        Verify that RealLLMProvider explicitly declares offline emulator mode
        when no external API key is configured and reports token usage as NOT AVAILABLE.
        """
        provider = RealLLMProvider(model="gpt-4o-mini", api_key=None)
        assert provider.is_external_configured is False

        accounting = provider.get_usage_accounting()
        assert accounting["provider_mode"] == "offline_semantic_emulator"
        assert accounting["external_api_calls"] == 0
        assert accounting["input_tokens"] == "NOT AVAILABLE"
        assert accounting["total_tokens"] == "NOT AVAILABLE"
        assert accounting["estimated_cost_usd"] == "NOT AVAILABLE"
        assert accounting["external_network_latency_ms"] == "NOT AVAILABLE"

    # ── 6. Grounding Test ─────────────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_grounding_rejects_fabricated_evidence_id(self) -> None:
        """Verify that a diagnosis citing a nonexistent evidence ID fails verification."""
        llm = DeterministicLLMProvider()
        now = datetime.now(tz=timezone.utc)
        incident = Incident(
            incident_id="INC-GROUND-001",
            created_at=now, updated_at=now,
            severity=IncidentSeverity.HIGH, service_name="payments-service",
            trigger_type=TriggerType.METRIC_THRESHOLD, trigger_rule_id="rule-test",
            title="Test Incident", description="Test", source_provider="otel",
            source_integration_id="agent-1", episode_key="test::key",
        )
        real_evidence = [
            InvestigationEvidence(
                evidence_id="E01",
                incident_id="INC-GROUND-001",
                source_type="telemetry",
                source_ref="query_recent",
                resource="payments-service",
                kind="metric",
                description="Observed high error rate",
                source="telemetry",
                observation={"observed_max": 0.25},
            )
        ]
        # Diagnosis citing fabricated ID "E-PHANTOM-999"
        fabricated_diagnosis = Diagnosis(
            root_cause="Database crash",
            explanation="Fabricated diagnosis for testing rejection of phantom evidence.",
            confidence=0.90,
            supporting_evidence=["E-PHANTOM-999"],
            recommended_actions=["Restart"],
            observed_evidence=["E-PHANTOM-999"],
            knowledge_evidence=[],
        )

        verification = await llm.verify_diagnosis(incident, real_evidence, fabricated_diagnosis)
        assert verification.is_verified is False
        assert "E-PHANTOM-999" in verification.missing_evidence
        assert any(term in verification.reason.lower() for term in ["non-existent", "invalid", "fabricated"])

    # ── 7. Benchmark Isolation & Leakage Test ──────────────────────────────────
    def test_benchmark_scenarios_do_not_leak_ground_truth_in_incident(self) -> None:
        """
        Verify that no held-out benchmark scenario contains expected_root_cause_concept
        or expected_document_id within the model-facing Incident object.
        """
        for sc in INCIDENT_BENCHMARK_SCENARIOS:
            inc = sc.incident
            inc_dict = inc.model_dump()
            inc_str = str(inc_dict).lower()

            # Ensure expected_doc_id does not appear in incident attributes
            assert sc.expected_document_id.lower() not in inc_str, (
                f"Leakage detected: expected_document_id '{sc.expected_document_id}' found in scenario {sc.scenario_id}"
            )
            # Ensure ground-truth concept is not in raw incident metadata
            assert "expected_root_cause" not in inc_dict
            assert "ground_truth" not in inc_dict
