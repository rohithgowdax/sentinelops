"""
Canonical Domain Models for SentinelOps Knowledge Base.

Defines provider-neutral representations for operational knowledge documents,
chunks, retrieval queries, and search results.

Invariants:
- Zero dependency on Qdrant, Milvus, Chroma, or specific vector search vendors.
- Strongly typed fields with Pydantic validation.
- Every chunk preserves document lineage, section hierarchy, and metadata.
"""
from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    """Canonical classification for operational knowledge documents."""

    RUNBOOK = "runbook"
    POSTMORTEM = "postmortem"
    ARCHITECTURE = "architecture"
    POLICY = "policy"
    RELEASE = "release"
    ADVERSARIAL = "adversarial"


class RetrievalMode(str, Enum):
    """Execution modes for knowledge retrieval."""

    DENSE_ONLY = "dense_only"
    SPARSE_ONLY = "sparse_only"
    HYBRID = "hybrid"
    HYBRID_PLUS_RERANK = "hybrid_plus_rerank"


class KnowledgeMetadata(BaseModel):
    """
    Validated frontmatter metadata for operational documents.
    """

    document_id: str
    document_type: DocumentType
    title: str
    service: str | None = None
    environment: str | None = None
    severity: str | None = None
    version: str | int = "1"
    tags: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class KnowledgeChunk(BaseModel):
    """
    Canonical knowledge chunk representation.

    Stored within vector indices and passed across retrieval boundaries.
    """

    chunk_id: str = Field(default_factory=lambda: f"CHK-{uuid4().hex[:8].upper()}")
    document_id: str
    document_type: DocumentType
    title: str = ""
    service: str | None = None
    environment: str | None = None
    severity: str | None = None
    section: str = "main"
    content: str
    source: str = ""
    chunk_index: int = 0
    total_chunks: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeQuery(BaseModel):
    """
    Domain query object for semantic and filtered knowledge retrieval.
    """

    query: str
    service: str | None = None
    environment: str | None = None
    severity: str | None = None
    document_type: DocumentType | None = None
    limit: int = Field(default=5, ge=1, le=50)
    mode: RetrievalMode = RetrievalMode.HYBRID
    filters: dict[str, Any] = Field(default_factory=dict)


class KnowledgeResult(BaseModel):
    """
    Individual search result returned by a KnowledgeProvider.
    """

    chunk_id: str
    document_id: str
    document_type: DocumentType
    title: str = ""
    service: str | None = None
    environment: str | None = None
    severity: str | None = None
    section: str = ""
    content: str
    source: str = ""
    score: float = 0.0
    rank: int = 1
    retrieval_mode: str = "hybrid"
    metadata: dict[str, Any] = Field(default_factory=dict)
