"""
Unit Tests for ApprovalService and Revalidation Semantics.
"""
from __future__ import annotations

import pytest

from sentinelops.approval.service import ApprovalService, ApprovalStatus
from sentinelops.domain.models.action import (
    ActionRequest,
    ActionType,
    RiskClass,
    TargetResource,
)
from sentinelops.domain.models.policy import (
    ActorContext,
    ActorRole,
    PolicyDecision,
    PolicyDecisionType,
)


class TestApprovalService:
    def setup_method(self) -> None:
        self.service = ApprovalService()
        self.target = TargetResource(resource_type="service", resource_id="payments-service")
        self.req = ActionRequest(
            action_id="ACT-APP-01",
            incident_id="INC-APP-01",
            action_type=ActionType.ROLLBACK_DEPLOYMENT,
            target=self.target,
            parameters={"target_version": "1.8.2"},
            rationale="Fix latency spike",
            environment="production",
        )
        self.decision = PolicyDecision(
            decision=PolicyDecisionType.REQUIRES_APPROVAL,
            reason="Production rollback requires incident commander",
            required_role=ActorRole.INCIDENT_COMMANDER,
            risk_class=RiskClass.HIGH,
        )

    def test_create_and_list_approval_request(self) -> None:
        app = self.service.create_request(self.req, self.decision)
        assert app.action_id == "ACT-APP-01"
        assert app.status == ApprovalStatus.PENDING
        assert app.required_role == ActorRole.INCIDENT_COMMANDER

        listed = self.service.list_approvals(ApprovalStatus.PENDING)
        assert len(listed) == 1
        assert listed[0].action_id == "ACT-APP-01"

    def test_unauthorized_actor_cannot_approve(self) -> None:
        self.service.create_request(self.req, self.decision)
        operator = ActorContext(actor_id="junior-op", role=ActorRole.OPERATOR)

        ok, msg, app = self.service.approve("ACT-APP-01", operator)
        assert ok is False
        assert "Unauthorized" in msg
        assert app.status == ApprovalStatus.PENDING

    def test_authorized_actor_approves(self) -> None:
        self.service.create_request(self.req, self.decision)
        ic = ActorContext(actor_id="lead-ic", role=ActorRole.INCIDENT_COMMANDER)

        ok, msg, app = self.service.approve("ACT-APP-01", ic, comment="Approved for rollback")
        assert ok is True
        assert app.status == ApprovalStatus.APPROVED
        assert app.resolved_by == "lead-ic"

    def test_revalidation_succeeds_and_enforces_one_time_use(self) -> None:
        self.service.create_request(self.req, self.decision)
        ic = ActorContext(actor_id="lead-ic", role=ActorRole.INCIDENT_COMMANDER)
        self.service.approve("ACT-APP-01", ic)

        # First revalidation: succeeds and consumes the approval
        ok, msg = self.service.revalidate_for_execution(self.req)
        assert ok is True
        assert "Execution authorized" in msg

        # Second revalidation with same action_id: fails because already consumed
        ok_dup, msg_dup = self.service.revalidate_for_execution(self.req)
        assert ok_dup is False
        assert "already been consumed" in msg_dup

    def test_revalidation_detects_parameter_tampering(self) -> None:
        self.service.create_request(self.req, self.decision)
        ic = ActorContext(actor_id="lead-ic", role=ActorRole.INCIDENT_COMMANDER)
        self.service.approve("ACT-APP-01", ic)

        # Adversarial tampering: action request parameters modified after approval
        tampered_req = ActionRequest(
            action_id="ACT-APP-01",
            incident_id="INC-APP-01",
            action_type=ActionType.ROLLBACK_DEPLOYMENT,
            target=self.target,
            parameters={"target_version": "1.9.9-malicious"},  # TAMPERED
            rationale="Tampered payload",
            environment="production",
        )

        ok, msg = self.service.revalidate_for_execution(tampered_req)
        assert ok is False
        assert "parameters altered" in msg
