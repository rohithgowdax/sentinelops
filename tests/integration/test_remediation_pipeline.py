"""
Integration Tests for SentinelOps Remediation Pipeline and Approval API.

Verifies end-to-end integration between:
1. Incident detection / intake
2. LangGraph AI investigation and remediation proposal
3. Policy evaluation gating production actions
4. FastAPI Approval REST API (list, get, approve with RBAC, reject)
5. Graph pause and resumption after API approval
6. Simulated ActionProvider execution and post-action verification
"""
from __future__ import annotations

from datetime import datetime, timezone
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from sentinelops.agent.graph import create_investigation_graph
from sentinelops.agent.state import InvestigationState
from sentinelops.approval.api import get_approval_service, router as approval_router
from sentinelops.approval.service import ApprovalService, ApprovalStatus
from sentinelops.audit.service import AuditService
from sentinelops.capabilities.llm.provider import DeterministicLLMProvider
from sentinelops.domain.models.action import ActionStatus
from sentinelops.domain.models.investigation import InvestigationStatus
from sentinelops.domain.models.policy import ActorRole
from sentinelops.integrations.actions.mock_deployment import MockServiceDeploymentProvider
from sentinelops.policy.engine import PolicyEngine
from tests.unit.test_remediation_graph import (
    _make_mock_evidence_provider,
    _make_test_incident,
)


@pytest.fixture
def test_approval_service() -> ApprovalService:
    return ApprovalService()


@pytest.fixture
def api_client(test_approval_service: ApprovalService) -> TestClient:
    app = FastAPI(title="SentinelOps Approval API Test")
    app.include_router(approval_router, prefix="/api/v1")
    app.dependency_overrides[get_approval_service] = lambda: test_approval_service
    return TestClient(app)


class TestRemediationPipelineIntegration:
    """Integration test suite for approval REST API and full remediation pipeline."""

    def test_approval_api_lifecycle(
        self,
        api_client: TestClient,
        test_approval_service: ApprovalService,
    ) -> None:
        """
        Verify REST endpoints:
        GET /api/v1/approvals (empty, then listed)
        GET /api/v1/approvals/{id}
        POST /api/v1/approvals/{id}/approve (403 for unauthorized, 200 for authorized)
        POST /api/v1/approvals/{id}/approve again (400 for already resolved)
        """
        # 1. Initial list should be empty
        resp = api_client.get("/api/v1/approvals")
        assert resp.status_code == 200
        assert resp.json() == []

        # 2. Trigger an action requiring approval by evaluating a production action
        engine = PolicyEngine()
        incident = _make_test_incident(env="production", service="payments-service")
        from sentinelops.domain.models.action import ActionRequest, ActionType, TargetResource
        action_req = ActionRequest(
            action_id="ACT-API-TEST-01",
            incident_id=incident.incident_id,
            action_type=ActionType.ROLLBACK_DEPLOYMENT,
            target=TargetResource(
                resource_type="service",
                resource_id="payments-service",
                environment="production",
            ),
            parameters={"target_version": "1.8.2"},
            rationale="Test approval API flow",
        )
        decision = engine.evaluate(action_req)
        assert decision.requires_approval is True
        test_approval_service.create_request(action_req, decision)

        # 3. List should now have 1 pending request
        resp = api_client.get("/api/v1/approvals")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["action_id"] == "ACT-API-TEST-01"
        assert items[0]["status"] == "pending"

        # 4. Get specific approval
        resp = api_client.get("/api/v1/approvals/ACT-API-TEST-01")
        assert resp.status_code == 200
        assert resp.json()["required_role"] == "incident_commander"

        # 5. Unauthorized actor attempts approval (role: operator -> 403 Forbidden)
        unauth_payload = {
            "actor_id": "operator-01",
            "actor_role": "operator",
            "reason": "Trying to approve without IC credentials",
        }
        resp = api_client.post("/api/v1/approvals/ACT-API-TEST-01/approve", json=unauth_payload)
        assert resp.status_code == 403
        assert "Unauthorized" in resp.json()["detail"]

        # 6. Authorized actor approves (role: incident_commander -> 200 OK)
        auth_payload = {
            "actor_id": "ic-lead-01",
            "actor_role": "incident_commander",
            "reason": "Verified rollback version 1.8.2 is safe.",
        }
        resp = api_client.post("/api/v1/approvals/ACT-API-TEST-01/approve", json=auth_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["resolved_by"] == "ic-lead-01"

        # 7. Repeated approval attempt should return 400 Bad Request (already resolved)
        resp = api_client.post("/api/v1/approvals/ACT-API-TEST-01/approve", json=auth_payload)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_full_pipeline_with_approval_api_resume(
        self,
        api_client: TestClient,
        test_approval_service: ApprovalService,
    ) -> None:
        """
        End-to-end integration test:
        1. Graph runs on production incident and pauses at await_approval.
        2. TestClient calls Approval API to approve the action.
        3. Graph is resumed with Command(resume={'status': 'approved'}).
        4. Mock action provider executes and verifies recovery.
        5. Graph completes with InvestigationStatus.RESOLVED.
        """
        incident = _make_test_incident(env="production", service="payments-service")
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
            approval_service=test_approval_service,
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

        config = {"configurable": {"thread_id": "test-e2e-pipeline-flow"}}

        # Step 1: Run graph to pause point
        paused_state = await graph.ainvoke(initial_state, config=config)
        action_req = paused_state["action_request"]
        assert action_req is not None
        assert paused_state["policy_decision"].requires_approval is True

        # Step 2: Use HTTP API client to approve
        approve_resp = api_client.post(
            f"/api/v1/approvals/{action_req.action_id}/approve",
            json={
                "actor_id": "lead-sre-01",
                "actor_role": "incident_commander",
                "reason": "Approved production remediation via API",
            },
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"] == "approved"

        # Step 3: Resume graph
        final_state = await graph.ainvoke(
            Command(resume={"status": "approved"}),
            config=config,
        )

        # Step 4: Verify full resolution
        assert final_state["status"] == InvestigationStatus.RESOLVED
        assert final_state["remediation_status"] == "resolved"
        assert final_state["action_result"].status == ActionStatus.SUCCEEDED
        assert final_state["remediation_verification"].is_recovered is True

        # Step 5: Verify audit trail contains full sequence of events
        trail = audit_service.get_incident_events(incident.incident_id)
        event_types = [e.event_type for e in trail]
        assert "action.proposed" in event_types
        assert "policy.evaluated" in event_types
        assert "action.revalidated" in event_types
        assert "action.started" in event_types
        assert "action.completed" in event_types
        assert "verification.completed" in event_types
        assert "incident.resolved" in event_types
