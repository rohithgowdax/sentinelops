"""
Unit tests for SentinelOps Knowledge Domain Models and Evidence Extensions.
"""
from __future__ import annotations

from sentinelops.domain.models.investigation import (
    Diagnosis,
    InvestigationEvidence,
    InvestigationResult,
    InvestigationStatus,
)
from sentinelops.domain.models.knowledge import (
    DocumentType,
    KnowledgeChunk,
    KnowledgeMetadata,
    KnowledgeQuery,
    KnowledgeResult,
    RetrievalMode,
)


class TestKnowledgeDomainModels:
    """Test suite for canonical knowledge and evidence models."""

    def test_document_types(self) -> None:
        """Verify supported document types."""
        types = [t.value for t in DocumentType]
        assert "runbook" in types
        assert "postmortem" in types
        assert "architecture" in types
        assert "policy" in types
        assert "release" in types
        assert "adversarial" in types

    def test_knowledge_metadata_validation(self) -> None:
        """Verify frontmatter metadata model."""
        meta = KnowledgeMetadata(
            document_id="rb-db-001",
            document_type=DocumentType.RUNBOOK,
            title="Postgres Runbook",
            service="payments-service",
            environment="production",
            severity="critical",
        )
        assert meta.document_id == "rb-db-001"
        assert meta.document_type == DocumentType.RUNBOOK

    def test_knowledge_chunk_model(self) -> None:
        """Verify canonical knowledge chunk model."""
        chunk = KnowledgeChunk(
            document_id="rb-db-001",
            document_type=DocumentType.RUNBOOK,
            title="PostgreSQL Runbook",
            section="Diagnostic Steps",
            content="Check active connection pool status.",
            source="knowledge/runbooks/rb-db-001.md",
        )
        assert chunk.chunk_id.startswith("CHK-")
        assert chunk.section == "Diagnostic Steps"
        assert chunk.document_type == DocumentType.RUNBOOK

    def test_knowledge_query_and_result(self) -> None:
        """Verify knowledge query parameters and result mapping."""
        query = KnowledgeQuery(
            query="database connection pool exhaustion",
            service="payments-service",
            mode=RetrievalMode.HYBRID,
            limit=5,
        )
        assert query.limit == 5
        assert query.mode == RetrievalMode.HYBRID

        result = KnowledgeResult(
            chunk_id="CHK-1234",
            document_id="rb-db-001",
            document_type=DocumentType.RUNBOOK,
            title="PostgreSQL Runbook",
            section="Resolution",
            content="Restart backend pods.",
            score=0.88,
            rank=1,
            retrieval_mode="hybrid",
        )
        assert result.rank == 1
        assert result.score == 0.88

    def test_investigation_evidence_knowledge_fields(self) -> None:
        """Verify InvestigationEvidence distinguishes knowledge and telemetry."""
        ev = InvestigationEvidence(
            evidence_id="EK01",
            incident_id="INC-001",
            source_type="knowledge",
            source_ref="rb-db-001",
            resource="payments-service",
            relevance="Operational runbook for connection exhaustion",
            kind="knowledge",
            document_id="rb-db-001",
            chunk_id="CHK-001",
            retrieval_score=0.91,
            rank=1,
            content_snippet="Pool connections maxed out",
        )
        assert ev.kind == "knowledge"
        assert ev.document_id == "rb-db-001"
        assert ev.retrieval_score == 0.91

    def test_diagnosis_evidence_separation(self) -> None:
        """Verify Diagnosis cleanly isolates observed vs knowledge evidence."""
        diag = Diagnosis(
            root_cause="Database connection exhaustion",
            confidence=0.92,
            supporting_evidence=["E01", "EK01"],
            observed_evidence=["E01"],
            knowledge_evidence=["EK01"],
            explanation="Telemetry correlates with runbook rb-db-001.",
            reasoning_summary="Correlated 1 telemetry signal with 1 runbook.",
            recommended_actions=["Restart leaking pods"],
        )
        assert diag.observed_evidence == ["E01"]
        assert diag.knowledge_evidence == ["EK01"]
        assert len(diag.supporting_evidence) == 2
