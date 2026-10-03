"""
Unit Tests for Action, Policy, and Verification Domain Models.
"""
from __future__ import annotations

from datetime import datetime, timezone
import pytest

from sentinelops.domain.models.action import (
    ActionRequest,
    ActionResult,
    ActionStatus,
    ActionType,
    RiskClass,
    TargetResource,
)
from sentinelops.domain.models.policy import (
    ActorContext,
    ActorRole,
    PolicyDecision,
    PolicyDecisionType,
    PolicyRule,
    ROLE_HIERARCHY,
)
from sentinelops.domain.models.verification import (
    MetricCheckResult,
    RemediationStatus,
    RemediationVerificationResult,
)


class TestActionDomainModels:
    def test_action_request_creation_and_defaults(self) -> None:
        target = TargetResource(resource_type="service", resource_id="payments-service")
        req = ActionRequest(
            incident_id="INC-101",
            action_type=ActionType.ROLLBACK_DEPLOYMENT,
            target=target,
            parameters={"target_version": "1.8.2"},
            rationale="Resolve connection leak introduced in v1.8.3",
            supporting_evidence=["E01", "E02"],
        )
        assert req.action_id.startswith("ACT-")
        assert req.environment == "production"
        assert req.risk_class == RiskClass.MEDIUM
        assert req.confidence == 1.0
        assert req.parameters["target_version"] == "1.8.2"

    def test_action_result_creation(self) -> None:
        res = ActionResult(
            action_id="ACT-101",
            status=ActionStatus.SUCCEEDED,
            provider="mock_deployment",
            result={"status": "healthy"},
        )
        assert res.status == ActionStatus.SUCCEEDED
        assert res.error is None
        assert res.completed_at is None


class TestPolicyDomainModels:
    def test_actor_role_hierarchy(self) -> None:
        op = ActorContext(actor_id="user-op", role=ActorRole.OPERATOR)
        sre = ActorContext(actor_id="user-sre", role=ActorRole.SRE)
        ic = ActorContext(actor_id="user-ic", role=ActorRole.INCIDENT_COMMANDER)
        admin = ActorContext(actor_id="user-admin", role=ActorRole.ADMIN)

        # Operator can satisfy Operator, but not SRE or IC
        assert op.has_sufficient_role(ActorRole.OPERATOR) is True
        assert op.has_sufficient_role(ActorRole.SRE) is False
        assert op.has_sufficient_role(ActorRole.INCIDENT_COMMANDER) is False

        # SRE can satisfy Operator and SRE, but not IC
        assert sre.has_sufficient_role(ActorRole.OPERATOR) is True
        assert sre.has_sufficient_role(ActorRole.SRE) is True
        assert sre.has_sufficient_role(ActorRole.INCIDENT_COMMANDER) is False

        # Incident Commander satisfies IC, SRE, Operator
        assert ic.has_sufficient_role(ActorRole.INCIDENT_COMMANDER) is True
        assert ic.has_sufficient_role(ActorRole.SRE) is True

        # Admin satisfies all
        assert admin.has_sufficient_role(ActorRole.INCIDENT_COMMANDER) is True

    def test_policy_decision_properties(self) -> None:
        dec = PolicyDecision(
            decision=PolicyDecisionType.REQUIRES_APPROVAL,
            reason="High risk production rollback",
            required_role=ActorRole.INCIDENT_COMMANDER,
            risk_class=RiskClass.HIGH,
        )
        assert dec.requires_approval is True
        assert dec.is_allowed is False
        assert dec.is_denied is False


class TestVerificationDomainModels:
    def test_remediation_verification_model(self) -> None:
        checks = [
            MetricCheckResult(
                metric_name="http.error_rate",
                before_value=0.18,
                after_value=0.007,
                threshold=0.05,
                improved=True,
                healthy=True,
                detail="Dropped to 0.7%",
            )
        ]
        ver = RemediationVerificationResult(
            incident_id="INC-101",
            action_id="ACT-101",
            status=RemediationStatus.RECOVERED,
            checks=checks,
            explanation="Operational telemetry recovered",
        )
        assert ver.is_recovered is True
        assert len(ver.checks) == 1
