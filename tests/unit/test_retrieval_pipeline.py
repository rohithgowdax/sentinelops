"""
Unit tests for SentinelOps Embedding, BM25, Reranker, and In-Memory Retrieval Pipeline.
"""
from __future__ import annotations

import math
import pytest

from sentinelops.capabilities.knowledge.embeddings import DeterministicEmbeddingProvider
from sentinelops.capabilities.knowledge.reranker import CrossFeatureReranker
from sentinelops.capabilities.knowledge.sparse import BM25Encoder
from sentinelops.domain.models.knowledge import (
    DocumentType,
    KnowledgeChunk,
    KnowledgeQuery,
    RetrievalMode,
)
from sentinelops.integrations.knowledge.in_memory_provider import (
    InMemoryKnowledgeProvider,
    _cosine_similarity,
)


class TestEmbeddingProvider:
    """Test suite for DeterministicEmbeddingProvider."""

    @pytest.mark.asyncio
    async def test_deterministic_embedding_properties(self) -> None:
        embedder = DeterministicEmbeddingProvider(dimension=128)
        assert embedder.dimension == 128

        v1 = await embedder.embed_query("PostgreSQL connection pool maxed out")
        v2 = await embedder.embed_query("PostgreSQL connection pool maxed out")
        assert len(v1) == 128
        assert v1 == v2

        # L2 norm is 1.0
        norm = math.sqrt(sum(x * x for x in v1))
        assert abs(norm - 1.0) < 1e-4

    @pytest.mark.asyncio
    async def test_semantic_cosine_similarity(self) -> None:
        embedder = DeterministicEmbeddingProvider(dimension=128)
        v_db1 = await embedder.embed_query("PostgreSQL connection pool exhaustion")
        v_db2 = await embedder.embed_query("Database pool connections exhausted")
        v_cake = await embedder.embed_query("Strawberry cheesecake recipe dessert")

        sim_related = _cosine_similarity(v_db1, v_db2)
        sim_unrelated = _cosine_similarity(v_db1, v_cake)

        assert sim_related > sim_unrelated


class TestBM25Encoder:
    """Test suite for BM25 lexical encoder."""

    def test_bm25_scoring(self) -> None:
        bm25 = BM25Encoder()
        docs = [
            "PostgreSQL database connection pool exhaustion troubleshooting steps",
            "Redis cache eviction memory saturation and stampede",
            "Canary deployment rollback procedure and git diff check",
        ]
        bm25.fit(docs)

        score_db = bm25.score("PostgreSQL connection pool", docs[0])
        score_cache = bm25.score("PostgreSQL connection pool", docs[1])

        assert score_db > score_cache
        assert score_cache == 0.0


class TestReranker:
    """Test suite for CrossFeatureReranker."""

    @pytest.mark.asyncio
    async def test_reranker_boosts_high_value_sections(self) -> None:
        reranker = CrossFeatureReranker()
        from sentinelops.domain.models.knowledge import KnowledgeResult

        r1 = KnowledgeResult(
            chunk_id="CHK-1",
            document_id="rb-db-001",
            document_type=DocumentType.RUNBOOK,
            title="Database Runbook",
            section="General Overview",
            content="This is general information about database infrastructure.",
            score=0.40,
            rank=1,
        )
        r2 = KnowledgeResult(
            chunk_id="CHK-2",
            document_id="rb-db-001",
            document_type=DocumentType.RUNBOOK,
            title="Database Runbook",
            section="Root Cause and Resolution",
            content="Root cause is connection exhaustion. Resolution: restart leaking worker pods.",
            score=0.38,
            rank=2,
        )

        reranked = await reranker.rerank(
            query="database connection exhaustion resolution",
            results=[r1, r2],
            top_k=2,
        )

        assert len(reranked) == 2
        # r2 should be promoted to rank 1 due to high-value section and keyword overlap
        assert reranked[0].chunk_id == "CHK-2"
        assert reranked[0].rank == 1


class TestInMemoryKnowledgeProvider:
    """Test suite for InMemoryKnowledgeProvider."""

    @pytest.fixture
    def sample_chunks(self) -> list[KnowledgeChunk]:
        return [
            KnowledgeChunk(
                chunk_id="CHK-DB-01",
                document_id="rb-db-001",
                document_type=DocumentType.RUNBOOK,
                title="Postgres Connection Pool",
                service="payments-service",
                environment="production",
                severity="critical",
                section="Diagnostic Steps",
                content="Check active connection pool slots. If 100/100, restart leaking workers.",
                source="knowledge/runbooks/rb-db-001.md",
            ),
            KnowledgeChunk(
                chunk_id="CHK-DEP-01",
                document_id="rb-deploy-005",
                document_type=DocumentType.RUNBOOK,
                title="Canary Rollback Procedure",
                service="payments-service",
                environment="production",
                severity="high",
                section="Resolution",
                content="Rollback image tag to v2.3.9 immediately to restore error rate baseline.",
                source="knowledge/runbooks/rb-deploy-005.md",
            ),
            KnowledgeChunk(
                chunk_id="CHK-CACHE-01",
                document_id="rb-cache-006",
                document_type=DocumentType.RUNBOOK,
                title="Redis Cache Eviction",
                service="shared-cache",
                environment="production",
                severity="medium",
                section="Mitigation",
                content="Increase maxmemory limit or evict keys with volatile-lru.",
                source="knowledge/runbooks/rb-cache-006.md",
            ),
        ]

    @pytest.mark.asyncio
    async def test_indexing_and_search_modes(self, sample_chunks: list[KnowledgeChunk]) -> None:
        provider = InMemoryKnowledgeProvider()
        indexed = await provider.index_chunks(sample_chunks)
        assert indexed == 3

        # Test dense_only
        q_dense = KnowledgeQuery(
            query="database connection pool exhausted",
            mode=RetrievalMode.DENSE_ONLY,
            limit=2,
        )
        res_dense = await provider.search(q_dense)
        assert len(res_dense) > 0
        assert res_dense[0].document_id == "rb-db-001"

        # Test sparse_only
        q_sparse = KnowledgeQuery(
            query="canary rollback procedure",
            mode=RetrievalMode.SPARSE_ONLY,
            limit=2,
        )
        res_sparse = await provider.search(q_sparse)
        assert len(res_sparse) > 0
        assert res_sparse[0].document_id == "rb-deploy-005"

        # Test hybrid
        q_hybrid = KnowledgeQuery(
            query="connection pool slots leaking workers",
            mode=RetrievalMode.HYBRID,
            limit=2,
        )
        res_hybrid = await provider.search(q_hybrid)
        assert len(res_hybrid) > 0
        assert res_hybrid[0].document_id == "rb-db-001"

    @pytest.mark.asyncio
    async def test_metadata_filtering(self, sample_chunks: list[KnowledgeChunk]) -> None:
        provider = InMemoryKnowledgeProvider()
        await provider.index_chunks(sample_chunks)

        # Filter by service="shared-cache"
        q_filtered = KnowledgeQuery(
            query="troubleshooting memory and connection issues",
            service="shared-cache",
            mode=RetrievalMode.HYBRID,
            limit=5,
        )
        res_filtered = await provider.search(q_filtered)
        assert len(res_filtered) == 1
        assert res_filtered[0].document_id == "rb-cache-006"
