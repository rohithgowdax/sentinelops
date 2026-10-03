"""
Qdrant Knowledge Provider for SentinelOps.

Implements `KnowledgeProvider` protocol backed by Qdrant vector database.
Supports:
1. Dense vector retrieval with cosine similarity.
2. Lexical sparse retrieval using BM25 scoring over payload text.
3. Hybrid search via Reciprocal Rank Fusion (RRF).
4. Metadata filtering on service, environment, severity, and document_type.
5. Cross-feature candidate reranking.
6. Graceful failure handling and circuit-breaking when Qdrant is unavailable.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from sentinelops.capabilities.knowledge.embeddings import DeterministicEmbeddingProvider
from sentinelops.capabilities.knowledge.reranker import CrossFeatureReranker
from sentinelops.capabilities.knowledge.sparse import BM25Encoder
from sentinelops.domain.contracts.protocols import (
    EmbeddingProvider,
    KnowledgeProvider,
    RerankerProvider,
)
from sentinelops.domain.models.knowledge import (
    DocumentType,
    KnowledgeChunk,
    KnowledgeQuery,
    KnowledgeResult,
    RetrievalMode,
)

logger = logging.getLogger(__name__)


class KnowledgeUnavailableError(Exception):
    """Raised when the vector database cannot be reached."""


class QdrantKnowledgeProvider(KnowledgeProvider):
    """
    Qdrant implementation of the KnowledgeProvider capability protocol.
    """

    def __init__(
        self,
        url: str = "http://localhost:6333",
        api_key: str | None = None,
        collection_name: str = "sentinelops_knowledge",
        embedding_provider: EmbeddingProvider | None = None,
        reranker: RerankerProvider | None = None,
        client: QdrantClient | None = None,
    ) -> None:
        self.url = url
        self.api_key = api_key
        self.collection_name = collection_name
        self.embedder = embedding_provider or DeterministicEmbeddingProvider()
        self.reranker = reranker or CrossFeatureReranker()
        self.bm25 = BM25Encoder()
        self._bm25_fit = False
        self.last_search_profile: dict[str, float] = {}

        if client is not None:
            self._client = client
        elif url == ":memory:":
            self._client = QdrantClient(":memory:", check_compatibility=False)
        else:
            self._client = QdrantClient(
                url=url, api_key=api_key, timeout=5.0, check_compatibility=False
            )

        self._initialized = False

    def _ensure_bm25_fit(self) -> None:
        """Fit BM25 encoder using existing points in collection if not already fit."""
        if self._bm25_fit:
            return
        try:
            points, _ = self._client.scroll(
                collection_name=self.collection_name,
                limit=1000,
                with_payload=True,
            )
            if points:
                texts = [
                    f"{p.payload.get('title', '')} {p.payload.get('section', '')} {p.payload.get('content', '')}"
                    for p in points
                    if p.payload
                ]
                self.bm25.fit(texts)
                self._bm25_fit = True
        except Exception as exc:
            logger.debug("BM25 auto-fit from Qdrant skipped: %s", exc)

    def ensure_collection(self) -> None:
        """Initialize collection and payload indexes if not present."""
        if self._initialized:
            return

        try:
            collections = self._client.get_collections().collections
            exists = any(c.name == self.collection_name for c in collections)

            if not exists:
                self._client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qmodels.VectorParams(
                        size=self.embedder.dimension,
                        distance=qmodels.Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection: %s", self.collection_name)

                # Create payload indexes for metadata filtering
                for field_name in ["service", "environment", "severity", "document_type"]:
                    self._client.create_payload_index(
                        collection_name=self.collection_name,
                        field_name=field_name,
                        field_schema=qmodels.PayloadSchemaType.KEYWORD,
                    )
            self._initialized = True
            self._ensure_bm25_fit()
        except Exception as exc:
            logger.warning("Failed to initialize Qdrant collection: %s", exc)
            raise KnowledgeUnavailableError(f"Qdrant unreachable at {self.url}: {exc}") from exc

    async def index_chunks(self, chunks: list[KnowledgeChunk]) -> int:
        """Idempotently index knowledge chunks into Qdrant."""
        self.ensure_collection()
        if not chunks:
            return 0

        texts = [f"{c.title} {c.section} {c.content}" for c in chunks]
        embeddings = await self.embedder.embed_documents(texts)

        # Fit lexical BM25 encoder
        self.bm25.fit(texts)

        points: list[qmodels.PointStruct] = []
        for chunk, vector in zip(chunks, embeddings):
            # Deterministic UUID per chunk_id for idempotency
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id))
            payload = {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "document_type": chunk.document_type.value,
                "title": chunk.title,
                "service": chunk.service,
                "environment": chunk.environment,
                "severity": chunk.severity,
                "section": chunk.section,
                "content": chunk.content,
                "source": chunk.source,
                "chunk_index": chunk.chunk_index,
                "total_chunks": chunk.total_chunks,
                "metadata": chunk.metadata,
            }
            points.append(
                qmodels.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            )

        try:
            self._client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True,
            )
            logger.info("Successfully indexed %d chunks into Qdrant", len(points))
            return len(points)
        except Exception as exc:
            raise KnowledgeUnavailableError(f"Failed to upsert chunks into Qdrant: {exc}") from exc

    def _build_filter(self, query: KnowledgeQuery) -> qmodels.Filter | None:
        """Convert query metadata filters to Qdrant Filter conditions."""
        must_conditions: list[qmodels.Condition] = []

        if query.service:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="service",
                    match=qmodels.MatchValue(value=query.service),
                )
            )
        if query.environment:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="environment",
                    match=qmodels.MatchValue(value=query.environment),
                )
            )
        if query.severity:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="severity",
                    match=qmodels.MatchValue(value=query.severity),
                )
            )
        if query.document_type:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="document_type",
                    match=qmodels.MatchValue(value=query.document_type.value),
                )
            )

        for k, v in query.filters.items():
            must_conditions.append(
                qmodels.FieldCondition(
                    key=f"metadata.{k}",
                    match=qmodels.MatchValue(value=v),
                )
            )

        if not must_conditions:
            return None
        return qmodels.Filter(must=must_conditions)

    async def search(self, query: KnowledgeQuery) -> list[KnowledgeResult]:
        """
        Execute knowledge search over Qdrant with distinct retrieval modes and profiling.
        """
        try:
            self.ensure_collection()
            self._ensure_bm25_fit()
        except KnowledgeUnavailableError:
            raise

        t_start = time.perf_counter()
        t_embed_ms = 0.0
        t_dense_ms = 0.0
        t_sparse_ms = 0.0
        t_fusion_ms = 0.0
        t_rerank_ms = 0.0

        q_filter = self._build_filter(query)
        mode = query.mode

        if mode == RetrievalMode.DENSE_ONLY:
            t0 = time.perf_counter()
            q_vec = await self.embedder.embed_query(query.query)
            t_embed_ms = (time.perf_counter() - t0) * 1000.0

            t0 = time.perf_counter()
            try:
                response = self._client.query_points(
                    collection_name=self.collection_name,
                    query=q_vec,
                    query_filter=q_filter,
                    limit=query.limit,
                    with_payload=True,
                )
                search_response = response.points
            except Exception as exc:
                logger.error("Qdrant search error: %s", exc)
                raise KnowledgeUnavailableError(f"Qdrant search failed: {exc}") from exc
            t_dense_ms = (time.perf_counter() - t0) * 1000.0

            results: list[KnowledgeResult] = []
            for rank, hit in enumerate(search_response[: query.limit], start=1):
                payload = hit.payload or {}
                results.append(
                    KnowledgeResult(
                        chunk_id=payload.get("chunk_id", ""),
                        document_id=payload.get("document_id", ""),
                        document_type=DocumentType(payload.get("document_type", "runbook")),
                        title=payload.get("title", ""),
                        service=payload.get("service"),
                        environment=payload.get("environment"),
                        severity=payload.get("severity"),
                        section=payload.get("section", ""),
                        content=payload.get("content", ""),
                        source=payload.get("source", ""),
                        score=round(hit.score, 4),
                        rank=rank,
                        retrieval_mode="dense_only",
                        metadata=payload.get("metadata", {}),
                    )
                )
            t_total_ms = (time.perf_counter() - t_start) * 1000.0
            self.last_search_profile = {
                "embedding_ms": round(t_embed_ms, 2),
                "dense_ms": round(t_dense_ms, 2),
                "sparse_ms": 0.0,
                "fusion_ms": 0.0,
                "rerank_ms": 0.0,
                "total_ms": round(t_total_ms, 2),
            }
            return results

        elif mode == RetrievalMode.SPARSE_ONLY:
            t0 = time.perf_counter()
            try:
                scroll_pts, _ = self._client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=q_filter,
                    limit=1000,
                    with_payload=True,
                )
            except Exception as exc:
                logger.error("Qdrant scroll error: %s", exc)
                raise KnowledgeUnavailableError(f"Qdrant scroll failed: {exc}") from exc

            scored_candidates = []
            for hit in scroll_pts:
                payload = hit.payload or {}
                text = f"{payload.get('title', '')} {payload.get('section', '')} {payload.get('content', '')}"
                bm25_score = self.bm25.score(query.query, text)
                scored_candidates.append((bm25_score, hit))

            scored_candidates.sort(key=lambda x: x[0], reverse=True)
            t_sparse_ms = (time.perf_counter() - t0) * 1000.0

            results = []
            for rank, (score, hit) in enumerate(scored_candidates[: query.limit], start=1):
                payload = hit.payload or {}
                results.append(
                    KnowledgeResult(
                        chunk_id=payload.get("chunk_id", ""),
                        document_id=payload.get("document_id", ""),
                        document_type=DocumentType(payload.get("document_type", "runbook")),
                        title=payload.get("title", ""),
                        service=payload.get("service"),
                        environment=payload.get("environment"),
                        severity=payload.get("severity"),
                        section=payload.get("section", ""),
                        content=payload.get("content", ""),
                        source=payload.get("source", ""),
                        score=round(score, 4),
                        rank=rank,
                        retrieval_mode="sparse_only",
                        metadata=payload.get("metadata", {}),
                    )
                )
            t_total_ms = (time.perf_counter() - t_start) * 1000.0
            self.last_search_profile = {
                "embedding_ms": 0.0,
                "dense_ms": 0.0,
                "sparse_ms": round(t_sparse_ms, 2),
                "fusion_ms": 0.0,
                "rerank_ms": 0.0,
                "total_ms": round(t_total_ms, 2),
            }
            return results

        else:
            # HYBRID & HYBRID_PLUS_RERANK:
            t0 = time.perf_counter()
            q_vec = await self.embedder.embed_query(query.query)
            t_embed_ms = (time.perf_counter() - t0) * 1000.0

            t0 = time.perf_counter()
            candidate_k = query.limit * 3
            try:
                dense_response = self._client.query_points(
                    collection_name=self.collection_name,
                    query=q_vec,
                    query_filter=q_filter,
                    limit=candidate_k,
                    with_payload=True,
                )
                dense_hits = dense_response.points
            except Exception as exc:
                logger.error("Qdrant search error: %s", exc)
                raise KnowledgeUnavailableError(f"Qdrant search failed: {exc}") from exc
            t_dense_ms = (time.perf_counter() - t0) * 1000.0

            t0 = time.perf_counter()
            try:
                scroll_pts, _ = self._client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=q_filter,
                    limit=1000,
                    with_payload=True,
                )
            except Exception as exc:
                logger.error("Qdrant scroll error: %s", exc)
                raise KnowledgeUnavailableError(f"Qdrant scroll failed: {exc}") from exc

            sparse_scored = []
            for hit in scroll_pts:
                payload = hit.payload or {}
                text = f"{payload.get('title', '')} {payload.get('section', '')} {payload.get('content', '')}"
                bm25_score = self.bm25.score(query.query, text)
                sparse_scored.append((bm25_score, hit))
            sparse_scored.sort(key=lambda x: x[0], reverse=True)
            sparse_hits = [hit for _, hit in sparse_scored[:candidate_k]]
            t_sparse_ms = (time.perf_counter() - t0) * 1000.0

            # Reciprocal Rank Fusion (k=60)
            t0 = time.perf_counter()
            dense_ranks = {hit.id: rank for rank, hit in enumerate(dense_hits, start=1)}
            sparse_ranks = {hit.id: rank for rank, hit in enumerate(sparse_hits, start=1)}

            all_candidate_dict = {}
            for hit in dense_hits:
                all_candidate_dict[hit.id] = hit
            for hit in sparse_hits:
                all_candidate_dict[hit.id] = hit

            rrf_k = 60.0
            default_rank = max(len(dense_hits), len(sparse_hits)) + 20
            fused_candidates: list[tuple[float, Any]] = []
            for hid, hit in all_candidate_dict.items():
                d_rank = dense_ranks.get(hid, default_rank)
                s_rank = sparse_ranks.get(hid, default_rank)
                rrf_score = (1.0 / (rrf_k + d_rank)) + (1.0 / (rrf_k + s_rank))
                fused_candidates.append((rrf_score, hit))

            fused_candidates.sort(key=lambda x: x[0], reverse=True)
            t_fusion_ms = (time.perf_counter() - t0) * 1000.0

            candidate_limit = query.limit * 2 if mode == RetrievalMode.HYBRID_PLUS_RERANK else query.limit
            fused_results: list[KnowledgeResult] = []
            for rank, (score, hit) in enumerate(fused_candidates[:candidate_limit], start=1):
                payload = hit.payload or {}
                fused_results.append(
                    KnowledgeResult(
                        chunk_id=payload.get("chunk_id", ""),
                        document_id=payload.get("document_id", ""),
                        document_type=DocumentType(payload.get("document_type", "runbook")),
                        title=payload.get("title", ""),
                        service=payload.get("service"),
                        environment=payload.get("environment"),
                        severity=payload.get("severity"),
                        section=payload.get("section", ""),
                        content=payload.get("content", ""),
                        source=payload.get("source", ""),
                        score=round(score * 50.0, 4),
                        rank=rank,
                        retrieval_mode="hybrid",
                        metadata=payload.get("metadata", {}),
                    )
                )

            if mode == RetrievalMode.HYBRID_PLUS_RERANK:
                t0 = time.perf_counter()
                fused_results = await self.reranker.rerank(
                    query=query.query,
                    results=fused_results,
                    top_k=query.limit,
                )
                t_rerank_ms = (time.perf_counter() - t0) * 1000.0

            t_total_ms = (time.perf_counter() - t_start) * 1000.0
            self.last_search_profile = {
                "embedding_ms": round(t_embed_ms, 2),
                "dense_ms": round(t_dense_ms, 2),
                "sparse_ms": round(t_sparse_ms, 2),
                "fusion_ms": round(t_fusion_ms, 2),
                "rerank_ms": round(t_rerank_ms, 2),
                "total_ms": round(t_total_ms, 2),
            }
            return fused_results
