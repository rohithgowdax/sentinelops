"""
Graph flow tests for SentinelOps LangGraph AI Investigation Loop.

Tests:
1. Standard verified investigation flow -> status DIAGNOSED with evidence backing.
2. Re-investigation loop when verification fails initially.
3. Max iteration termination -> status INSUFFICIENT_EVIDENCE.
4. Durable state checkpointing per incident_id thread.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import MemorySaver

from sentinelops.agent.graph import create_investigation_graph
from sentinelops.agent.state import InvestigationState
from sentinelops.capabilities.llm.provider import DeterministicLLMProvider
from sentinelops.domain.models.incident import (
    EvidenceItem,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    TriggerType,
)
from sentinelops.domain.models.investigation import (
    Diagnosis,
    Hypothesis,
    InvestigationEvidence,
    InvestigationPlan,
    InvestigationResult,
    InvestigationStatus as InvStatus,
    InvestigationStep,
    VerificationResult,
)


@pytest.fixture
def sample_incident() -> Incident:
    now = datetime.now(tz=timezone.utc)
    return Incident(
        incident_id="INC-GRAPH-TEST-1",
        created_at=now,
        updated_at=now,
        service_name="billing-service",
        title="Elevated Error Rate Detected",
        description="HTTP error rate exceeded threshold 0.15",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.OPEN,
        trigger_type=TriggerType.METRIC_THRESHOLD,
        trigger_rule_id="rule-billing-errors",
        trigger_rule_name="Billing Service Error Spike",
        source_provider="otel",
        source_integration_id="int-otel",
        episode_key="rule-billing-errors::billing-service::production",
        initial_evidence=[
            EvidenceItem(
                kind="metric",
                description="Observed error rate 0.28 > threshold 0.15",
                value=0.28,
                attributes={"metric_name": "http.error_rate", "threshold": 0.15},
            )
        ],
    )


@pytest.fixture
def mock_evidence_provider() -> AsyncMock:
    provider = AsyncMock()
    provider.query_recent_telemetry.return_value = {
        "resource": "billing-service",
        "metric": "http.error_rate",
        "sample_count": 6,
        "observed_avg": 0.26,
        "observed_max": 0.32,
        "observed_min": 0.18,
        "latest_value": 0.30,
        "raw_references": ["evt-101", "evt-102"],
    }
    provider.compare_telemetry_baseline.return_value = {
        "resource": "billing-service",
        "metric": "http.error_rate",
        "baseline_avg": 0.02,
        "current_avg": 0.26,
        "elevation_ratio": 13.0,
        "is_elevated": True,
        "baseline_samples": 20,
        "current_samples": 6,
    }
    provider.get_incident_trigger_context.return_value = {
        "incident_id": "INC-GRAPH-TEST-1",
        "service_name": "billing-service",
        "initial_evidence": [{"kind": "metric", "value": 0.28}],
    }
    return provider


def _make_initial_state(incident: Incident, max_iterations: int = 3) -> InvestigationState:
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    return {
        "incident": incident,
        "investigation_plan": None,
        "current_step": 0,
        "iteration": 0,
        "max_iterations": max_iterations,
        "evidence": [],
        "hypotheses": [],
        "selected_hypothesis": None,
        "diagnosis": None,
        "confidence": 0.0,
        "verification_result": None,
        "status": InvStatus.INVESTIGATING,
        "errors": [],
        "tool_calls_summary": [],
        "start_time_iso": now_iso,
        "final_result": None,
    }


class TestInvestigationGraphFlow:
    """Test suite verifying end-to-end LangGraph execution paths."""

    @pytest.mark.asyncio
    async def test_standard_verified_investigation_flow(
        self,
        sample_incident: Incident,
        mock_evidence_provider: AsyncMock,
    ) -> None:
        """
        Verify happy-path investigation:
        intake -> plan -> collect -> analyze -> diagnose -> verify (pass) -> finalize.
        """
        checkpointer = MemorySaver()
        llm = DeterministicLLMProvider()
        graph = create_investigation_graph(
            evidence_provider=mock_evidence_provider,
            llm_provider=llm,
            checkpointer=checkpointer,
        )

        initial_state = _make_initial_state(sample_incident, max_iterations=3)
        config = {"configurable": {"thread_id": sample_incident.incident_id}}

        final_state = await graph.ainvoke(initial_state, config=config)

        # Assert final result structure
        result: InvestigationResult = final_state["final_result"]
        assert result is not None
        assert result.incident_id == sample_incident.incident_id
        assert result.status == InvStatus.DIAGNOSED
        assert result.confidence >= 0.80
        assert result.diagnosis is not None
        assert len(result.supporting_evidence) > 0

        # Assert evidence references are valid and non-empty
        for ev_id in result.diagnosis.supporting_evidence:
            matched = any(e.evidence_id == ev_id for e in result.supporting_evidence)
            assert matched, f"Diagnosis cited non-existent evidence ID: {ev_id}"

        # Assert tool calls occurred
        assert len(result.tool_calls_summary) > 0
        assert result.iteration_count == 1

    @pytest.mark.asyncio
    async def test_reinvestigation_loop_on_weak_evidence(
        self,
        sample_incident: Incident,
        mock_evidence_provider: AsyncMock,
    ) -> None:
        """
        Verify re-investigation loop when verifier rejects first iteration:
        verify (fail) -> collect -> analyze -> diagnose -> verify (pass) -> finalize.
        """
        checkpointer = MemorySaver()
        mock_llm = AsyncMock()

        # Step 1: Planning
        mock_llm.generate_plan.return_value = InvestigationPlan(
            steps=[
                InvestigationStep(
                    id="step1",
                    description="Check metrics",
                    capability="telemetry",
                    params={"metric_name": "http.error_rate"},
                )
            ]
        )

        # Step 2: Hypotheses
        mock_llm.analyze_hypotheses.return_value = [
            Hypothesis(
                hypothesis_id="H01",
                hypothesis="Service degraded",
                confidence=0.75,
                supporting_evidence_ids=["E01"],
            )
        ]

        # Step 3: Diagnosis
        mock_llm.generate_diagnosis.return_value = Diagnosis(
            root_cause="Service degraded by error burst",
            confidence=0.85,
            supporting_evidence=["E01"],
            explanation="Elevated failure metrics.",
            recommended_actions=["Scale up"],
        )

        # Step 4: Verifier: Fails on iteration 1, passes on iteration 2
        mock_llm.verify_diagnosis.side_effect = [
            VerificationResult(
                is_verified=False,
                confidence=0.40,
                reason="Insufficient samples during first pass",
                missing_evidence=["baseline_comparison"],
            ),
            VerificationResult(
                is_verified=True,
                confidence=0.90,
                reason="Adequate corroborating evidence on second pass",
            ),
        ]

        graph = create_investigation_graph(
            evidence_provider=mock_evidence_provider,
            llm_provider=mock_llm,
            checkpointer=checkpointer,
        )

        initial_state = _make_initial_state(sample_incident, max_iterations=3)
        config = {"configurable": {"thread_id": sample_incident.incident_id}}

        final_state = await graph.ainvoke(initial_state, config=config)
        result: InvestigationResult = final_state["final_result"]

        assert result.status == InvStatus.DIAGNOSED
        assert result.iteration_count == 2
        assert mock_llm.verify_diagnosis.call_count == 2

    @pytest.mark.asyncio
    async def test_max_iteration_termination_insufficient_evidence(
        self,
        sample_incident: Incident,
        mock_evidence_provider: AsyncMock,
    ) -> None:
        """
        Verify that graph halts at max_iterations if verification consistently fails,
        terminating with INSUFFICIENT_EVIDENCE status.
        """
        checkpointer = MemorySaver()
        mock_llm = AsyncMock()

        mock_llm.generate_plan.return_value = InvestigationPlan(
            steps=[
                InvestigationStep(
                    id="step1",
                    description="Check metrics",
                    capability="telemetry",
                    params={"metric_name": "http.error_rate"},
                )
            ]
        )
        mock_llm.analyze_hypotheses.return_value = [
            Hypothesis(
                hypothesis_id="H01",
                hypothesis="Transient spike",
                confidence=0.30,
                supporting_evidence_ids=["E01"],
            )
        ]
        mock_llm.generate_diagnosis.return_value = Diagnosis(
            root_cause="Inconclusive transient fluctuation",
            confidence=0.35,
            supporting_evidence=["E01"],
            explanation="Unclear root cause.",
            recommended_actions=["Continue monitoring"],
        )
        # Always fail verification
        mock_llm.verify_diagnosis.return_value = VerificationResult(
            is_verified=False,
            confidence=0.30,
            reason="Signal does not confirm persistent root cause.",
            missing_evidence=["downstream_traces"],
        )

        graph = create_investigation_graph(
            evidence_provider=mock_evidence_provider,
            llm_provider=mock_llm,
            checkpointer=checkpointer,
        )

        # Set max_iterations = 2 for fast test
        initial_state = _make_initial_state(sample_incident, max_iterations=2)
        config = {"configurable": {"thread_id": sample_incident.incident_id}}

        final_state = await graph.ainvoke(initial_state, config=config)
        result: InvestigationResult = final_state["final_result"]

        assert result.status == InvStatus.INSUFFICIENT_EVIDENCE
        assert result.iteration_count == 2
        assert result.failure_reason is not None
        assert "Signal does not confirm" in result.failure_reason

    @pytest.mark.asyncio
    async def test_state_checkpointing_per_thread_id(
        self,
        sample_incident: Incident,
        mock_evidence_provider: AsyncMock,
    ) -> None:
        """
        Verify that thread_id captures state checkpoint in MemorySaver checkpointer.
        """
        checkpointer = MemorySaver()
        llm = DeterministicLLMProvider()
        graph = create_investigation_graph(
            evidence_provider=mock_evidence_provider,
            llm_provider=llm,
            checkpointer=checkpointer,
        )

        initial_state = _make_initial_state(sample_incident, max_iterations=3)
        thread_id = sample_incident.incident_id
        config = {"configurable": {"thread_id": thread_id}}

        await graph.ainvoke(initial_state, config=config)

        # Query checkpoint state via graph's official API
        graph_state = await graph.aget_state(config)
        assert graph_state is not None
        saved_state = graph_state.values
        assert saved_state["incident"].incident_id == thread_id
        assert saved_state["final_result"] is not None
        assert saved_state["final_result"].status == InvStatus.DIAGNOSED
