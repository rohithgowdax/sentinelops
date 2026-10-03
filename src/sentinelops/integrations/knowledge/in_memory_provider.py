"""
In-Memory Knowledge Provider for SentinelOps.

Implements `KnowledgeProvider` protocol entirely in memory.
Used for:
1. Architectural generalization contract tests (proving zero vendor lock-in to Qdrant).
2. Fast, offline unit testing without external processes.
"""
from __future__ import annotations

import math
from typing import Any

from sentinelops.capabilities.knowledge.embeddings import DeterministicEmbeddingProvider
from sentinelops.capabilities.knowledge.reranker import CrossFeatureReranker
from sentinelops.capabilities.knowledge.sparse import BM25Encoder
from sentinelops.domain.contracts.protocols import (
    EmbeddingProvider,
    KnowledgeProvider,
    RerankerProvider,
)
from sentinelops.domain.models.knowledge import (
    KnowledgeChunk,
    KnowledgeQuery,
    KnowledgeResult,
    RetrievalMode,
)


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


class InMemoryKnowledgeProvider(KnowledgeProvider):
    """
    In-memory vector & lexical knowledge provider.
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        reranker: RerankerProvider | None = None,
    ) -> None:
        self._embedder = embedding_provider or DeterministicEmbeddingProvider()
        self._reranker = reranker or CrossFeatureReranker()
        self._chunks: dict[str, KnowledgeChunk] = {}
        self._embeddings: dict[str, list[float]] = {}
        self._bm25 = BM25Encoder()
        self._is_bm25_fit = False

    async def index_chunks(self, chunks: list[KnowledgeChunk]) -> int:
        """Idempotently index knowledge chunks."""
        count = 0
        texts_to_embed: list[str] = []
        chunk_ids_to_embed: list[str] = []

        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk
            texts_to_embed.append(f"{chunk.title} {chunk.section} {chunk.content}")
            chunk_ids_to_embed.append(chunk.chunk_id)
            count += 1

        if texts_to_embed:
            vectors = await self._embedder.embed_documents(texts_to_embed)
            for cid, vec in zip(chunk_ids_to_embed, vectors):
                self._embeddings[cid] = vec

        # Re-fit BM25 encoder over all contents
        all_docs = [f"{c.title} {c.section} {c.content}" for c in self._chunks.values()]
        self._bm25.fit(all_docs)
        self._is_bm25_fit = True
        return count

    def _matches_filters(self, chunk: KnowledgeChunk, query: KnowledgeQuery) -> bool:
        """Apply metadata filtering."""
        if query.service and chunk.service and query.service != chunk.service:
            return False
        if query.environment and chunk.environment and query.environment != chunk.environment:
            return False
        if query.severity and chunk.severity and query.severity != chunk.severity:
            return False
        if query.document_type and chunk.document_type != query.document_type:
            return False
        for k, v in query.filters.items():
            if chunk.metadata.get(k) != v:
                return False
        return True

    async def search(self, query: KnowledgeQuery) -> list[KnowledgeResult]:
        """Execute search in requested retrieval mode."""
        filtered_chunks = [
            c for c in self._chunks.values() if self._matches_filters(c, query)
        ]
        if not filtered_chunks:
            return []

        mode = query.mode
        q_vec = await self._embedder.embed_query(query.query)

        dense_scores: dict[str, float] = {}
        sparse_scores: dict[str, float] = {}

        for chunk in filtered_chunks:
            # Dense similarity
            c_vec = self._embeddings.get(chunk.chunk_id, [])
            dense_scores[chunk.chunk_id] = _cosine_similarity(q_vec, c_vec)

            # Sparse BM25 similarity
            doc_text = f"{chunk.title} {chunk.section} {chunk.content}"
            sparse_scores[chunk.chunk_id] = self._bm25.score(query.query, doc_text)

        # Build rankings
        results: list[KnowledgeResult] = []

        if mode == RetrievalMode.DENSE_ONLY:
            sorted_by_dense = sorted(
                filtered_chunks, key=lambda c: dense_scores[c.chunk_id], reverse=True
            )
            for rank, c in enumerate(sorted_by_dense[: query.limit], start=1):
                results.append(
                    KnowledgeResult(
                        chunk_id=c.chunk_id,
                        document_id=c.document_id,
                        document_type=c.document_type,
                        title=c.title,
                        service=c.service,
                        environment=c.environment,
                        severity=c.severity,
                        section=c.section,
                        content=c.content,
                        source=c.source,
                        score=round(dense_scores[c.chunk_id], 4),
                        rank=rank,
                        retrieval_mode="dense_only",
                        metadata=c.metadata,
                    )
                )

        elif mode == RetrievalMode.SPARSE_ONLY:
            sorted_by_sparse = sorted(
                filtered_chunks, key=lambda c: sparse_scores[c.chunk_id], reverse=True
            )
            for rank, c in enumerate(sorted_by_sparse[: query.limit], start=1):
                results.append(
                    KnowledgeResult(
                        chunk_id=c.chunk_id,
                        document_id=c.document_id,
                        document_type=c.document_type,
                        title=c.title,
                        service=c.service,
                        environment=c.environment,
                        severity=c.severity,
                        section=c.section,
                        content=c.content,
                        source=c.source,
                        score=round(sparse_scores[c.chunk_id], 4),
                        rank=rank,
                        retrieval_mode="sparse_only",
                        metadata=c.metadata,
                    )
                )

        else:
            # HYBRID or HYBRID_PLUS_RERANK via Reciprocal Rank Fusion (RRF)
            dense_ranked = sorted(
                filtered_chunks, key=lambda c: dense_scores[c.chunk_id], reverse=True
            )
            sparse_ranked = sorted(
                filtered_chunks, key=lambda c: sparse_scores[c.chunk_id], reverse=True
            )

            dense_ranks = {c.chunk_id: r for r, c in enumerate(dense_ranked, start=1)}
            sparse_ranks = {c.chunk_id: r for r, c in enumerate(sparse_ranked, start=1)}

            rrf_k = 60.0
            fused_scores: dict[str, float] = {}
            for chunk in filtered_chunks:
                cid = chunk.chunk_id
                score = (1.0 / (rrf_k + dense_ranks[cid])) + (1.0 / (rrf_k + sparse_ranks[cid]))
                fused_scores[cid] = score

            sorted_fused = sorted(
                filtered_chunks, key=lambda c: fused_scores[c.chunk_id], reverse=True
            )

            candidate_limit = query.limit * 2 if mode == RetrievalMode.HYBRID_PLUS_RERANK else query.limit
            for rank, c in enumerate(sorted_fused[:candidate_limit], start=1):
                results.append(
                    KnowledgeResult(
                        chunk_id=c.chunk_id,
                        document_id=c.document_id,
                        document_type=c.document_type,
                        title=c.title,
                        service=c.service,
                        environment=c.environment,
                        severity=c.severity,
                        section=c.section,
                        content=c.content,
                        source=c.source,
                        score=round(fused_scores[c.chunk_id] * 50.0, 4),  # Scale for readability
                        rank=rank,
                        retrieval_mode="hybrid",
                        metadata=c.metadata,
                    )
                )

            if mode == RetrievalMode.HYBRID_PLUS_RERANK:
                results = await self._reranker.rerank(
                    query=query.query,
                    results=results,
                    top_k=query.limit,
                )

        return results
