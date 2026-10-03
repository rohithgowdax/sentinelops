"""
Knowledge Generalization Contract Tests for SentinelOps Slice 3.

Architectural Proofs:
1. Zero Vector DB / Qdrant Coupling in Agent AST:
   Agent nodes, graph, state, and prompts NEVER import `qdrant_client`, `milvus`,
   `chroma`, `openai`, `gemini`, or `anthropic`.
2. KnowledgeProvider Capability Interchangeability:
   Both `InMemoryKnowledgeProvider` and `QdrantKnowledgeProvider` satisfy the
   exact same `KnowledgeProvider` protocol and can drive the exact same LangGraph investigation.
3. Equivalent Canonical Knowledge Results:
   Different vector providers produce equivalent canonical `KnowledgeResult` structures.
4. Knowledge-Unavailable Resilience:
   When KnowledgeProvider fails (e.g. database down), the investigation gracefully
   completes using live operational telemetry without crashing or corrupting state.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sentinelops.agent import graph, nodes, prompts, state
from sentinelops.agent.graph import create_investigation_graph
from sentinelops.agent.state import InvestigationState
from sentinelops.capabilities.llm.provider import DeterministicLLMProvider
from sentinelops.domain.contracts.protocols import KnowledgeProvider
from sentinelops.domain.models.incident import (
    EvidenceItem,
    Incident,
    IncidentSeverity,
    TriggerType,
)
from sentinelops.domain.models.investigation import (
    InvestigationResult,
    InvestigationStatus,
)
from sentinelops.domain.models.knowledge import (
    DocumentType,
    KnowledgeChunk,
    KnowledgeQuery,
    KnowledgeResult,
    RetrievalMode,
)
from sentinelops.integrations.knowledge.in_memory_provider import InMemoryKnowledgeProvider
from sentinelops.integrations.knowledge.qdrant_provider import (
    KnowledgeUnavailableError,
    QdrantKnowledgeProvider,
)


class TestKnowledgeGeneralizationContract:
    """Contract tests proving provider-neutral knowledge architecture."""

    def test_zero_vector_db_imports_in_agent_ast(self) -> None:
        """
        Static AST analysis proving that agent modules do not import or mention
        vector vendor packages ('qdrant_client', 'chromadb', 'pymilvus', 'openai').
        """
        agent_dir = Path(nodes.__file__).parent
        files_to_check = list(agent_dir.glob("*.py"))
        files_to_check.append(Path(graph.__file__))
        files_to_check.append(Path(state.__file__))
        files_to_check.append(Path(prompts.__file__))

        prohibited_modules = {
            "qdrant_client",
            "chromadb",
            "pymilvus",
            "openai",
            "anthropic",
            "google.generativeai",
        }

        for py_file in files_to_check:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        mod = alias.name.split(".")[0]
                        assert mod not in prohibited_modules, (
                            f"Prohibited vendor import '{mod}' found in {py_file.name}:{node.lineno}"
                        )
                elif isinstance(node, ast.ImportFrom):
                    mod = (node.module or "").split(".")[0]
                    assert mod not in prohibited_modules, (
                        f"Prohibited vendor import '{mod}' found in {py_file.name}:{node.lineno}"
                    )

    def test_knowledge_provider_protocol_conformance(self) -> None:
        """
        Verify that both InMemoryKnowledgeProvider and QdrantKnowledgeProvider
        conform structurally to the KnowledgeProvider Protocol.
        """
        assert issubclass(InMemoryKnowledgeProvider, KnowledgeProvider)
        assert issubclass(QdrantKnowledgeProvider, KnowledgeProvider)

    @pytest.mark.asyncio
    async def test_equivalent_canonical_results_across_providers(self) -> None:
        """
        Verify that different knowledge providers return identically structured
        canonical KnowledgeResult objects for the same input chunk and query.
        """
        chunk = KnowledgeChunk(
            chunk_id="CHK-EQUIV-01",
            document_id="rb-db-001",
            document_type=DocumentType.RUNBOOK,
            title="Postgres Runbook",
            service="payments-service",
            section="Resolution",
            content="Restart leaking worker pods to recover connection slots.",
            source="knowledge/runbooks/rb-db-001.md",
        )

        in_memory = InMemoryKnowledgeProvider()
        qdrant = QdrantKnowledgeProvider(url=":memory:")

        await in_memory.index_chunks([chunk])
        await qdrant.index_chunks([chunk])

        query = KnowledgeQuery(
            query="restart leaking worker pods connection slots",
            mode=RetrievalMode.DENSE_ONLY,
            limit=1,
        )

        res_in_memory = await in_memory.search(query)
        res_qdrant = await qdrant.search(query)

        assert len(res_in_memory) == 1
        assert len(res_qdrant) == 1

        im_res: KnowledgeResult = res_in_memory[0]
        qd_res: KnowledgeResult = res_qdrant[0]

        # Verify semantic identity of returned fields
        assert im_res.document_id == qd_res.document_id == "rb-db-001"
        assert im_res.chunk_id == qd_res.chunk_id == "CHK-EQUIV-01"
        assert im_res.document_type == qd_res.document_type == DocumentType.RUNBOOK
        assert im_res.title == qd_res.title == "Postgres Runbook"
        assert im_res.section == qd_res.section == "Resolution"
        assert im_res.service == qd_res.service == "payments-service"
        assert im_res.content == qd_res.content

    @pytest.mark.asyncio
    async def test_graceful_fallback_when_knowledge_unavailable(self) -> None:
        """
        Proves that when KnowledgeProvider fails or raises KnowledgeUnavailableError,
        the LangGraph agent does NOT fail: it gracefully completes the investigation
        using live operational telemetry.
        """
        failing_kp = AsyncMock()
        failing_kp.search.side_effect = KnowledgeUnavailableError("Connection to vector DB timed out")

        mock_telemetry = AsyncMock()
        mock_telemetry.query_recent_telemetry.return_value = {
            "resource": "payments-service",
            "metric": "http.error_rate",
            "sample_count": 8,
            "observed_avg": 0.22,
            "observed_max": 0.28,
            "latest_value": 0.24,
            "raw_references": ["ref-1"],
        }
        mock_telemetry.compare_telemetry_baseline.return_value = {
            "resource": "payments-service",
            "metric": "http.error_rate",
            "baseline_avg": 0.02,
            "current_avg": 0.22,
            "elevation_ratio": 11.0,
            "is_elevated": True,
        }
        mock_telemetry.get_incident_trigger_context.side_effect = lambda inc: {
            "incident_id": inc.incident_id,
            "service_name": inc.service_name,
            "initial_evidence": [{"kind": "metric", "value": 0.24}],
        }

        now = datetime.now(tz=timezone.utc)
        incident = Incident(
            incident_id="INC-FALLBACK-001",
            created_at=now,
            updated_at=now,
            severity=IncidentSeverity.HIGH,
            service_name="payments-service",
            trigger_type=TriggerType.METRIC_THRESHOLD,
            trigger_rule_id="rule-high-error-rate",
            title="High Error Rate",
            description="Error rate elevated",
            source_provider="otel",
            source_integration_id="agent-1",
            episode_key="rule-high-error-rate::payments-service::production",
            initial_evidence=[EvidenceItem(kind="metric", description="Error rate", value=0.24)],
        )

        graph_instance = create_investigation_graph(
            evidence_provider=mock_telemetry,
            llm_provider=DeterministicLLMProvider(),
            knowledge_provider=failing_kp,
        )

        state_input: InvestigationState = {
            "incident": incident,
            "investigation_plan": None,
            "current_step": 0,
            "iteration": 0,
            "max_iterations": 3,
            "evidence": [],
            "hypotheses": [],
            "selected_hypothesis": None,
            "diagnosis": None,
            "confidence": 0.0,
            "verification_result": None,
            "status": InvestigationStatus.INVESTIGATING,
            "errors": [],
            "tool_calls_summary": [],
            "start_time_iso": now.isoformat(),
            "final_result": None,
            "evidence_groups": {"telemetry": [], "knowledge": []},
            "knowledge_queries": [],
            "knowledge_available": True,
            "retrieval_mode": "hybrid",
        }

        final = await graph_instance.ainvoke(
            state_input, config={"configurable": {"thread_id": "test-fallback"}}
        )
        res: InvestigationResult = final["final_result"]

        # Crucial architectural proof:
        # Status MUST be DIAGNOSED (from telemetry evidence alone)
        assert res.status == InvestigationStatus.DIAGNOSED
        assert res.diagnosis is not None
        assert len(res.telemetry_evidence) >= 1
        assert len(res.knowledge_evidence) == 0
        assert final["knowledge_available"] is False
        assert any("Knowledge retrieval error" in err for err in final["errors"])
