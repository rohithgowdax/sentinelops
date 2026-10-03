"""
Unit tests for individual LangGraph investigation nodes in isolation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import time
from unittest.mock import AsyncMock

import pytest

from sentinelops.agent.nodes.analyzer import make_analyzer_node
from sentinelops.agent.nodes.collector import make_collector_node
from sentinelops.agent.nodes.diagnoser import make_diagnoser_node
from sentinelops.agent.nodes.finalizer import finalize
from sentinelops.agent.nodes.intake import incident_intake
from sentinelops.agent.nodes.planner import make_planner_node
from sentinelops.agent.nodes.verifier import make_verifier_node, route_after_verification
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
    InvestigationStatus as InvStatus,
    InvestigationStep,
    InvestigationResult,
    VerificationResult,
)


@pytest.fixture
def sample_incident() -> Incident:
    now = datetime.now(tz=timezone.utc)
    return Incident(
        incident_id="INC-TEST-1",
        created_at=now,
        updated_at=now,
        service_name="payment-svc",
        title="High Error Rate",
        description="Triggered by error rate rule",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.OPEN,
        trigger_type=TriggerType.METRIC_THRESHOLD,
        trigger_rule_id="rule-payment-error-rate",
        trigger_rule_name="Payment Errors",
        source_provider="otel",
        source_integration_id="int-otel",
        episode_key="rule-payment-error-rate::payment-svc::prod",
        initial_evidence=[
            EvidenceItem(
                kind="metric",
                description="Observed error rate 0.22",
                value=0.22,
                attributes={"metric_name": "http.error_rate"},
            )
        ],
    )


@pytest.fixture
def base_state(sample_incident: Incident) -> InvestigationState:
    return {
        "incident": sample_incident,
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
        "status": InvStatus.INVESTIGATING,
        "errors": [],
        "tool_calls_summary": [],
        "start_time_iso": datetime.now(tz=timezone.utc).isoformat(),
        "final_result": None,
    }


class TestInvestigationNodes:
    """Test suite verifying isolated node state transitions."""

    def test_incident_intake(self, base_state: InvestigationState) -> None:
        """Verify intake initializes iteration counter and logs transition."""
        delta = incident_intake(base_state)
        assert delta["iteration"] == 0
        assert delta["status"] == InvStatus.INVESTIGATING
        assert "start_time_iso" in delta

    @pytest.mark.asyncio
    async def test_planner_node(self, base_state: InvestigationState) -> None:
        """Verify planner returns structured InvestigationPlan."""
        llm = DeterministicLLMProvider()
        planner_node = make_planner_node(llm)

        delta = await planner_node(base_state)
        plan = delta["investigation_plan"]
        assert isinstance(plan, InvestigationPlan)
        assert len(plan.steps) > 0
        assert delta["current_step"] == 0

    @pytest.mark.asyncio
    async def test_collector_node(self, base_state: InvestigationState) -> None:
        """Verify collector queries evidence provider and gathers evidence."""
        mock_evidence_provider = AsyncMock()
        mock_evidence_provider.query_recent_telemetry.return_value = {
            "resource": "payment-svc",
            "metric": "http.error_rate",
            "sample_count": 5,
            "observed_avg": 0.20,
            "observed_max": 0.25,
            "observed_min": 0.15,
            "latest_value": 0.25,
            "raw_references": ["evt-1"],
        }
        mock_evidence_provider.compare_telemetry_baseline.return_value = {}
        mock_evidence_provider.get_incident_trigger_context.return_value = {}

        plan = InvestigationPlan(
            steps=[
                InvestigationStep(
                    id="step1",
                    description="Check error rate",
                    capability="telemetry",
                    params={"metric_name": "http.error_rate"},
                )
            ]
        )
        base_state["investigation_plan"] = plan

        collector_node = make_collector_node(mock_evidence_provider)
        delta = await collector_node(base_state)

        assert len(delta["evidence"]) == 1
        assert delta["evidence"][0].signal == "http.error_rate"
        assert len(delta["tool_calls_summary"]) == 1
        assert delta["iteration"] == 1

    @pytest.mark.asyncio
    async def test_analyzer_node(self, base_state: InvestigationState) -> None:
        """Verify analyzer produces hypotheses referencing evidence."""
        llm = DeterministicLLMProvider()
        ev = InvestigationEvidence(
            evidence_id="E001",
            incident_id="INC-TEST-1",
            source_type="telemetry",
            source_ref="http.error_rate",
            resource="payment-svc",
            signal="http.error_rate",
            observation={"observed_max": 0.25, "avg_value": 0.20},
        )
        base_state["evidence"] = [ev]

        analyzer_node = make_analyzer_node(llm)
        delta = await analyzer_node(base_state)

        hypotheses = delta["hypotheses"]
        assert len(hypotheses) > 0
        assert "E001" in hypotheses[0].supporting_evidence_ids
        assert delta["selected_hypothesis"] is not None

    @pytest.mark.asyncio
    async def test_diagnoser_node(self, base_state: InvestigationState) -> None:
        """Verify diagnoser constructs a valid Diagnosis."""
        llm = DeterministicLLMProvider()
        ev = InvestigationEvidence(
            evidence_id="E001",
            incident_id="INC-TEST-1",
            source_type="telemetry",
            source_ref="http.error_rate",
            resource="payment-svc",
            signal="http.error_rate",
            observation={"observed_max": 0.25, "avg_value": 0.20},
        )
        hyp = Hypothesis(
            hypothesis="Payment service downstream timeouts",
            confidence=0.85,
            supporting_evidence_ids=["E001"],
        )
        base_state["evidence"] = [ev]
        base_state["hypotheses"] = [hyp]
        base_state["selected_hypothesis"] = hyp

        diagnoser_node = make_diagnoser_node(llm)
        delta = await diagnoser_node(base_state)

        diagnosis = delta["diagnosis"]
        assert isinstance(diagnosis, Diagnosis)
        assert "E001" in diagnosis.supporting_evidence
        assert diagnosis.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_verifier_node(self, base_state: InvestigationState) -> None:
        """Verify verifier validates diagnosis against evidence."""
        llm = DeterministicLLMProvider()
        ev = InvestigationEvidence(
            evidence_id="E001",
            incident_id="INC-TEST-1",
            source_type="telemetry",
            source_ref="http.error_rate",
            resource="payment-svc",
            signal="http.error_rate",
            observation={"observed_max": 0.25, "avg_value": 0.20},
        )
        diag = Diagnosis(
            root_cause="Service error anomaly",
            confidence=0.85,
            supporting_evidence=["E001"],
            explanation="Elevated failure metrics.",
            recommended_actions=["Inspect logs"],
        )
        base_state["evidence"] = [ev]
        base_state["diagnosis"] = diag

        verifier_node = make_verifier_node(llm)
        delta = await verifier_node(base_state)

        vr = delta["verification_result"]
        assert isinstance(vr, VerificationResult)
        assert vr.is_verified is True

    def test_route_after_verification(self, base_state: InvestigationState) -> None:
        """Verify routing conditional edge logic."""
        # Case 1: Verified -> finalize
        base_state["verification_result"] = VerificationResult(
            is_verified=True,
            confidence=0.85,
            reason="Verified with high confidence",
        )
        base_state["iteration"] = 1
        assert route_after_verification(base_state) == "finalize"

        # Case 2: Not verified, under limit -> collect_evidence
        base_state["verification_result"] = VerificationResult(
            is_verified=False,
            confidence=0.30,
            reason="Insufficient evidence",
        )
        base_state["iteration"] = 1
        base_state["max_iterations"] = 3
        assert route_after_verification(base_state) == "collect_evidence"

        # Case 3: Not verified, max iterations reached -> finalize
        base_state["verification_result"] = VerificationResult(
            is_verified=False,
            confidence=0.30,
            reason="Max iterations reached",
        )
        base_state["iteration"] = 3
        base_state["max_iterations"] = 3
        assert route_after_verification(base_state) == "finalize"

    def test_finalize_node(self, base_state: InvestigationState) -> None:
        """Verify finalize produces immutable InvestigationResult."""
        diag = Diagnosis(
            root_cause="Payment service error surge",
            confidence=0.90,
            supporting_evidence=["E001"],
            explanation="Failure rates exceeded baseline.",
            recommended_actions=["Restart instance"],
        )
        base_state["diagnosis"] = diag
        base_state["verification_result"] = VerificationResult(
            is_verified=True,
            confidence=0.90,
            reason="Strong supporting evidence",
        )
        base_state["iteration"] = 1

        delta = finalize(base_state)
        result = delta["final_result"]

        assert isinstance(result, InvestigationResult)
        assert result.status == InvStatus.DIAGNOSED
        assert result.confidence == 0.90
        assert result.diagnosis is not None
        assert result.diagnosis.root_cause == "Payment service error surge"

