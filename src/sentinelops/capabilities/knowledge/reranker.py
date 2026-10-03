"""
Reranker implementations for SentinelOps Knowledge Retrieval.

Implements `RerankerProvider` protocol to re-score candidate knowledge chunks
based on cross-feature lexical alignment, section relevance, and metadata matching.
"""
from __future__ import annotations

import re
from typing import Any

from sentinelops.domain.contracts.protocols import RerankerProvider
from sentinelops.domain.models.knowledge import KnowledgeResult


class CrossFeatureReranker(RerankerProvider):
    """
    Reranker combining lexical overlap, heading priority, and metadata alignment.
    """

    # High-value diagnosis sections in operational runbooks & postmortems
    _HIGH_VALUE_SECTIONS = {
        "root cause",
        "resolution",
        "investigation",
        "diagnosis",
        "remediation",
        "symptoms",
        "mitigation",
        "action items",
    }

    def _tokenize(self, text: str) -> set[str]:
        clean = re.sub(r"[^\w\s]", " ", text.lower())
        return {t for t in clean.split() if len(t) > 2}

    async def rerank(
        self,
        query: str,
        results: list[KnowledgeResult],
        top_k: int = 5,
    ) -> list[KnowledgeResult]:
        """
        Rerank and filter candidate search results.
        """
        if not results:
            return []

        q_tokens = self._tokenize(query)
        scored_items: list[tuple[float, KnowledgeResult]] = []

        for res in results:
            content_tokens = self._tokenize(res.content)
            title_tokens = self._tokenize(res.title)
            section_tokens = self._tokenize(res.section)

            # 1. Base vector/fusion score (scaled 0..0.4)
            base_score = min(0.4, max(0.0, res.score * 0.4))

            # 2. Lexical overlap ratio (scaled 0..0.3)
            overlap = len(q_tokens.intersection(content_tokens.union(title_tokens)))
            lexical_score = min(0.3, (overlap / max(1, len(q_tokens))) * 0.3)

            # 3. High-priority section boost (0.15)
            section_lower = res.section.lower()
            section_boost = 0.0
            for sec in self._HIGH_VALUE_SECTIONS:
                if sec in section_lower:
                    section_boost = 0.15
                    break

            # 4. Title / Summary keyword match boost (0.15)
            title_overlap = len(q_tokens.intersection(title_tokens))
            title_boost = 0.15 if title_overlap > 0 else 0.0

            total_score = base_score + lexical_score + section_boost + title_boost

            # Create updated KnowledgeResult with new score
            reranked_res = KnowledgeResult(
                chunk_id=res.chunk_id,
                document_id=res.document_id,
                document_type=res.document_type,
                title=res.title,
                service=res.service,
                environment=res.environment,
                severity=res.severity,
                section=res.section,
                content=res.content,
                source=res.source,
                score=round(total_score, 4),
                rank=res.rank,
                retrieval_mode=f"{res.retrieval_mode}+rerank",
                metadata=res.metadata,
            )
            scored_items.append((total_score, reranked_res))

        # Sort descending by total score
        scored_items.sort(key=lambda x: x[0], reverse=True)

        # Slice to top_k and re-assign rank 1..k
        reranked_results: list[KnowledgeResult] = []
        for rank, (_, item) in enumerate(scored_items[:top_k], start=1):
            item.rank = rank
            reranked_results.append(item)

        return reranked_results
