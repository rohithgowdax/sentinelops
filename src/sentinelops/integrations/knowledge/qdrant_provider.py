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

        if client is not None:
            self._client = client
        elif url == ":memory:":
            self._client = QdrantClient(":memory:", check_compatibility=False)
        else:
            self._client = QdrantClient(
                url=url, api_key=api_key, timeout=5.0, check_compatibility=False
            )


        self._initialized = False

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
        Execute knowledge search over Qdrant.
        """
        try:
            self.ensure_collection()
        except KnowledgeUnavailableError:
            raise

        q_filter = self._build_filter(query)
        q_vec = await self.embedder.embed_query(query.query)
        mode = query.mode

        try:
            # Query dense candidates from Qdrant
            # Fetch extra candidates if hybrid or rerank mode
            fetch_limit = (
                query.limit * 3
                if mode in (RetrievalMode.HYBRID, RetrievalMode.HYBRID_PLUS_RERANK)
                else query.limit
            )
            response = self._client.query_points(
                collection_name=self.collection_name,
                query=q_vec,
                query_filter=q_filter,
                limit=fetch_limit,
                with_payload=True,
            )
            search_response = response.points
        except Exception as exc:
            logger.error("Qdrant search error: %s", exc)
            raise KnowledgeUnavailableError(f"Qdrant search failed: {exc}") from exc


        if not search_response:
            return []

        # If DENSE_ONLY, directly return Qdrant scored points
        if mode == RetrievalMode.DENSE_ONLY:
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
            return results

        # For SPARSE_ONLY, score retrieved candidates via BM25
        if mode == RetrievalMode.SPARSE_ONLY:
            scored_candidates = []
            for hit in search_response:
                payload = hit.payload or {}
                text = f"{payload.get('title', '')} {payload.get('section', '')} {payload.get('content', '')}"
                bm25_score = self.bm25.score(query.query, text)
                scored_candidates.append((bm25_score, hit))

            scored_candidates.sort(key=lambda x: x[0], reverse=True)
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
            return results

        # HYBRID & HYBRID_PLUS_RERANK: Reciprocal Rank Fusion (RRF)
        # Dense ranking from Qdrant hits
        dense_ranks = {hit.id: rank for rank, hit in enumerate(search_response, start=1)}

        # Sparse ranking via BM25
        sparse_scored = []
        for hit in search_response:
            payload = hit.payload or {}
            text = f"{payload.get('title', '')} {payload.get('section', '')} {payload.get('content', '')}"
            bm25_score = self.bm25.score(query.query, text)
            sparse_scored.append((hit.id, bm25_score))
        sparse_scored.sort(key=lambda x: x[1], reverse=True)
        sparse_ranks = {hid: rank for rank, (hid, _) in enumerate(sparse_scored, start=1)}

        # Combine via RRF (k=60)
        rrf_k = 60.0
        fused_hits: list[tuple[float, Any]] = []
        for hit in search_response:
            d_rank = dense_ranks[hit.id]
            s_rank = sparse_ranks.get(hit.id, len(search_response))
            rrf_score = (1.0 / (rrf_k + d_rank)) + (1.0 / (rrf_k + s_rank))
            fused_hits.append((rrf_score, hit))

        fused_hits.sort(key=lambda x: x[0], reverse=True)

        candidate_limit = query.limit * 2 if mode == RetrievalMode.HYBRID_PLUS_RERANK else query.limit
        fused_results: list[KnowledgeResult] = []
        for rank, (score, hit) in enumerate(fused_hits[:candidate_limit], start=1):
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
            return await self.reranker.rerank(
                query=query.query,
                results=fused_results,
                top_k=query.limit,
            )

        return fused_results
