"""
Unit and Flow Tests for SentinelOps LangGraph Controlled Remediation Workflow.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
import pytest

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from sentinelops.agent.graph import create_investigation_graph
from sentinelops.agent.state import InvestigationState
from sentinelops.approval.service import ApprovalService
from sentinelops.audit.service import AuditService
from sentinelops.capabilities.llm.provider import DeterministicLLMProvider
from sentinelops.domain.models.action import ActionRequest, ActionType, TargetResource
from sentinelops.domain.models.incident import (
    EvidenceItem,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    TriggerType,
)
from sentinelops.domain.models.investigation import InvestigationStatus
from sentinelops.domain.models.policy import (
    ActorContext,
    ActorRole,
    PolicyDecisionType,
    PolicyRule,
)
from sentinelops.integrations.actions.mock_deployment import (
    MockServiceDeploymentProvider,
)
from sentinelops.policy.engine import PolicyEngine


def _make_test_incident(env: str = "production", service: str = "payments-service") -> Incident:
    now = datetime.now(tz=timezone.utc)
    return Incident(
        incident_id=f"INC-{env}-01",
        created_at=now,
        updated_at=now,
        severity=IncidentSeverity.HIGH,
        service_name=service,
        environment=env,
        trigger_type=TriggerType.METRIC_THRESHOLD,
        trigger_rule_id="rule-01",
        trigger_rule_name="Elevated Error Rate",
        title=f"Elevated Error Rate on {service}",
        description="Observed error rate 18.4% exceeding threshold 5%",
        source_provider="otel",
        source_integration_id="test",
        episode_key=f"rule-01::{service}::{env}",
        initial_evidence=[
            EvidenceItem(
                kind="metric",
                description="http.error_rate = 0.184",
                value=0.184,
                attributes={"metric_name": "http.error_rate", "threshold": 0.05},
            )
        ],
    )


def _make_mock_evidence_provider(service: str = "payments-service") -> AsyncMock:
    ev_prov = AsyncMock()
    ev_prov.query_recent_telemetry.return_value = {
        "resource": service,
        "metric": "http.error_rate",
        "sample_count": 10,
        "observed_avg": 0.184,
        "observed_max": 0.22,
        "observed_min": 0.15,
        "latest_value": 0.184,
        "raw_references": ["ref-1", "ref-2"],
    }
    ev_prov.compare_telemetry_baseline.return_value = {
        "resource": service,
        "metric": "http.error_rate",
        "sample_count": 30,
        "baseline_avg": 0.01,
        "baseline_stddev": 0.002,
        "elevation_ratio": 18.4,
    }
    ev_prov.get_incident_trigger_context.side_effect = lambda inc: {
        "incident_id": inc.incident_id,
        "service_name": inc.service_name,
        "initial_evidence": [
            {"kind": "metric", "value": item.value, "description": item.description}
            for item in inc.initial_evidence
        ],
    }
    return ev_prov


class TestRemediationGraphFlow:
    @pytest.mark.asyncio
    async def test_staging_automated_remediation_flow(self) -> None:
        """
        In staging, policy allows automated rollback -> executes -> verifies -> resolves.
        """
        incident = _make_test_incident(env="staging", service="payments-service")
        ev_prov = _make_mock_evidence_provider("payments-service")
        action_prov = MockServiceDeploymentProvider()
        policy_engine = PolicyEngine()
        audit_service = AuditService()
        checkpointer = MemorySaver()

        graph = create_investigation_graph(
            evidence_provider=ev_prov,
            llm_provider=DeterministicLLMProvider(),
            action_provider=action_prov,
            policy_engine=policy_engine,
            audit_service=audit_service,
            checkpointer=checkpointer,
        )

        initial_state: InvestigationState = {
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
            "start_time_iso": datetime.now(tz=timezone.utc).isoformat(),
            "final_result": None,
            "evidence_groups": {"telemetry": [], "knowledge": []},
            "knowledge_queries": [],
            "knowledge_available": False,
            "retrieval_mode": "hybrid",
            "action_request": None,
            "policy_decision": None,
            "action_result": None,
            "remediation_verification": None,
            "remediation_attempts": 0,
            "max_remediation_attempts": 2,
            "remediation_status": "idle",
        }

        config = {"configurable": {"thread_id": "test-staging-flow-01"}}
        final_state = await graph.ainvoke(initial_state, config=config)

        # Assertions
        assert final_state["status"] == InvestigationStatus.RESOLVED
        assert final_state["remediation_status"] == "resolved"
        assert final_state["action_request"] is not None
        assert final_state["policy_decision"].is_allowed is True
        assert final_state["action_result"].status.value == "succeeded"
        assert final_state["remediation_verification"].is_recovered is True

        # Check audit trail
        events = [e.event_type for e in audit_service.get_events_for_incident(incident.incident_id)]
        assert "action.proposed" in events
        assert "policy.evaluated" in events
        assert "action.started" in events
        assert "action.completed" in events
        assert "verification.completed" in events
        assert "incident.resolved" in events

    @pytest.mark.asyncio
    async def test_production_remediation_requires_approval_and_resumes(self) -> None:
        """
        In production, rollback requires approval:
        Graph pauses at await_approval -> operator approves via ApprovalService -> resumes -> executes -> resolves.
        """
        incident = _make_test_incident(env="production", service="payments-service")
        ev_prov = _make_mock_evidence_provider("payments-service")
        action_prov = MockServiceDeploymentProvider()
        policy_engine = PolicyEngine()
        approval_service = ApprovalService()
        audit_service = AuditService()
        checkpointer = MemorySaver()

        graph = create_investigation_graph(
            evidence_provider=ev_prov,
            llm_provider=DeterministicLLMProvider(),
            action_provider=action_prov,
            policy_engine=policy_engine,
            approval_service=approval_service,
            audit_service=audit_service,
            checkpointer=checkpointer,
        )

        initial_state: InvestigationState = {
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
            "start_time_iso": datetime.now(tz=timezone.utc).isoformat(),
            "final_result": None,
            "evidence_groups": {"telemetry": [], "knowledge": []},
            "knowledge_queries": [],
            "knowledge_available": False,
            "retrieval_mode": "hybrid",
            "action_request": None,
            "policy_decision": None,
            "action_result": None,
            "remediation_verification": None,
            "remediation_attempts": 0,
            "max_remediation_attempts": 2,
            "remediation_status": "idle",
        }

        config = {"configurable": {"thread_id": "test-prod-approval-flow"}}

        # 1. Run until interruption
        interrupted_state = await graph.ainvoke(initial_state, config=config)

        # Graph should have proposed an action and required approval
        action_req = interrupted_state["action_request"]
        assert action_req is not None
        assert interrupted_state["policy_decision"].requires_approval is True

        # Check pending approval in approval service
        approval = approval_service.get_approval(action_req.action_id)
        assert approval is not None
        assert approval.status.value == "pending"

        # 2. Operator approves via ApprovalService
        ic_actor = ActorContext(actor_id="lead-ic", role=ActorRole.INCIDENT_COMMANDER)
        approved_ok, _, _ = approval_service.approve(action_req.action_id, ic_actor)
        assert approved_ok is True

        # 3. Resume the graph with approved signal
        resumed_state = await graph.ainvoke(
            Command(resume={"status": "approved"}),
            config=config,
        )

        assert resumed_state["status"] == InvestigationStatus.RESOLVED
        assert resumed_state["remediation_status"] == "resolved"
        assert resumed_state["action_result"].status.value == "succeeded"

    @pytest.mark.asyncio
    async def test_policy_denial_prevents_any_execution(self) -> None:
        """
        When policy denies an action (e.g. destructive rule), action provider is never called.
        """
        incident = _make_test_incident(env="production", service="payments-service")
        ev_prov = _make_mock_evidence_provider("payments-service")
        action_prov = MockServiceDeploymentProvider()
        
        # Policy configured to universally deny all rollback actions
        custom_engine = PolicyEngine(
            rules=[
                PolicyRule(
                    rule_id="RULE-DENY-ALL-ROLLBACKS",
                    action_type="rollback_deployment",
                    environment="*",
                    decision=PolicyDecisionType.DENY,
                    description="Change freeze in effect; all rollbacks denied.",
                )
            ]
        )
        audit_service = AuditService()
        checkpointer = MemorySaver()

        graph = create_investigation_graph(
            evidence_provider=ev_prov,
            llm_provider=DeterministicLLMProvider(),
            action_provider=action_prov,
            policy_engine=custom_engine,
            audit_service=audit_service,
            checkpointer=checkpointer,
        )

        initial_state: InvestigationState = {
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
            "start_time_iso": datetime.now(tz=timezone.utc).isoformat(),
            "final_result": None,
            "evidence_groups": {"telemetry": [], "knowledge": []},
            "knowledge_queries": [],
            "knowledge_available": False,
            "retrieval_mode": "hybrid",
            "action_request": None,
            "policy_decision": None,
            "action_result": None,
            "remediation_verification": None,
            "remediation_attempts": 0,
            "max_remediation_attempts": 2,
            "remediation_status": "idle",
        }

        config = {"configurable": {"thread_id": "test-deny-flow"}}
        final_state = await graph.ainvoke(initial_state, config=config)

        assert final_state["remediation_status"] == "denied"
        # Zero actions executed on action provider
        assert len(action_prov._executed_actions) == 0
