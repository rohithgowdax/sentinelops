"""
Unit tests for QdrantKnowledgeProvider using in-memory Qdrant instance.
"""
from __future__ import annotations

import pytest

from sentinelops.domain.models.knowledge import (
    DocumentType,
    KnowledgeChunk,
    KnowledgeQuery,
    RetrievalMode,
)
from sentinelops.integrations.knowledge.qdrant_provider import (
    KnowledgeUnavailableError,
    QdrantKnowledgeProvider,
)


class TestQdrantKnowledgeProvider:
    """Test suite for Qdrant vector store integration."""

    @pytest.fixture
    def in_memory_provider(self) -> QdrantKnowledgeProvider:
        provider = QdrantKnowledgeProvider(
            url=":memory:",
            collection_name="test_knowledge",
        )
        provider.ensure_collection()
        return provider

    @pytest.fixture
    def sample_chunks(self) -> list[KnowledgeChunk]:
        return [
            KnowledgeChunk(
                chunk_id="CHK-Q-01",
                document_id="rb-db-001",
                document_type=DocumentType.RUNBOOK,
                title="PostgreSQL Runbook",
                service="payments-service",
                environment="production",
                severity="critical",
                section="Diagnostic Steps",
                content="Check active connection pool slots. If 100/100, restart leaking workers.",
                source="knowledge/runbooks/rb-db-001.md",
            ),
            KnowledgeChunk(
                chunk_id="CHK-Q-02",
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
        ]

    @pytest.mark.asyncio
    async def test_indexing_and_dense_search(
        self,
        in_memory_provider: QdrantKnowledgeProvider,
        sample_chunks: list[KnowledgeChunk],
    ) -> None:
        indexed = await in_memory_provider.index_chunks(sample_chunks)
        assert indexed == 2

        query = KnowledgeQuery(
            query="PostgreSQL connection pool maxed out",
            mode=RetrievalMode.DENSE_ONLY,
            limit=2,
        )
        results = await in_memory_provider.search(query)
        assert len(results) > 0
        assert results[0].document_id == "rb-db-001"
        assert results[0].retrieval_mode == "dense_only"

    @pytest.mark.asyncio
    async def test_hybrid_and_reranking(
        self,
        in_memory_provider: QdrantKnowledgeProvider,
        sample_chunks: list[KnowledgeChunk],
    ) -> None:
        await in_memory_provider.index_chunks(sample_chunks)

        query = KnowledgeQuery(
            query="rollback image tag v2.3.9 error rate baseline",
            mode=RetrievalMode.HYBRID_PLUS_RERANK,
            limit=2,
        )
        results = await in_memory_provider.search(query)
        assert len(results) > 0
        assert results[0].document_id == "rb-deploy-005"
        assert "rerank" in results[0].retrieval_mode

    @pytest.mark.asyncio
    async def test_metadata_filtering_on_qdrant(
        self,
        in_memory_provider: QdrantKnowledgeProvider,
        sample_chunks: list[KnowledgeChunk],
    ) -> None:
        await in_memory_provider.index_chunks(sample_chunks)

        query = KnowledgeQuery(
            query="troubleshooting",
            severity="critical",
            limit=5,
        )
        results = await in_memory_provider.search(query)
        assert len(results) == 1
        assert results[0].document_id == "rb-db-001"

    @pytest.mark.asyncio
    async def test_unreachable_host_raises_knowledge_unavailable(self) -> None:
        """Verify graceful error mapping when Qdrant host is unreachable."""
        bad_provider = QdrantKnowledgeProvider(
            url="http://127.0.0.1:59999",  # Non-existent port
            collection_name="fail_collection",
        )
        query = KnowledgeQuery(query="test query")
        with pytest.raises(KnowledgeUnavailableError):
            await bad_provider.search(query)
