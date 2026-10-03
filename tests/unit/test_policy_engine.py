"""
Unit Tests for Deterministic PolicyEngine.
"""
from __future__ import annotations

import pytest

from sentinelops.domain.models.action import (
    ActionRequest,
    ActionType,
    RiskClass,
    TargetResource,
)
from sentinelops.domain.models.policy import (
    ActorContext,
    ActorRole,
    PolicyDecisionType,
)
from sentinelops.policy.engine import PolicyEngine


class TestPolicyEngine:
    def setup_method(self) -> None:
        self.engine = PolicyEngine()

    def test_risk_evaluation_classification(self) -> None:
        target = TargetResource(resource_type="service", resource_id="payments-service")

        # Critical: destructive action
        req_crit = ActionRequest(
            incident_id="INC-1",
            action_type=ActionType.DELETE_RESOURCE,
            target=target,
            rationale="test",
        )
        assert self.engine.evaluate_risk(req_crit) == RiskClass.CRITICAL

        # High: prod rollback
        req_high = ActionRequest(
            incident_id="INC-1",
            action_type=ActionType.ROLLBACK_DEPLOYMENT,
            target=target,
            environment="production",
            rationale="test",
        )
        assert self.engine.evaluate_risk(req_high) == RiskClass.HIGH

        # Medium: prod restart
        req_med = ActionRequest(
            incident_id="INC-1",
            action_type=ActionType.RESTART_SERVICE,
            target=target,
            environment="production",
            rationale="test",
        )
        assert self.engine.evaluate_risk(req_med) == RiskClass.MEDIUM

        # Low: staging rollback
        req_low = ActionRequest(
            incident_id="INC-1",
            action_type=ActionType.ROLLBACK_DEPLOYMENT,
            target=target,
            environment="staging",
            rationale="test",
        )
        assert self.engine.evaluate_risk(req_low) == RiskClass.LOW

    def test_destructive_actions_universally_denied(self) -> None:
        target = TargetResource(resource_type="service", resource_id="payments-service")
        for bad_action in [
            ActionType.DELETE_RESOURCE,
            ActionType.MODIFY_DATABASE,
            ActionType.EXECUTE_COMMAND,
            ActionType.RUN_SHELL,
        ]:
            req = ActionRequest(
                incident_id="INC-1",
                action_type=bad_action,
                target=target,
                environment="staging",  # Even in staging, destructive actions are DENIED
                rationale="adversarial prompt",
            )
            decision = self.engine.evaluate(req)
            assert decision.decision == PolicyDecisionType.DENY
            assert decision.risk_class == RiskClass.CRITICAL
            assert "prohibited" in decision.reason.lower()

    def test_staging_actions_automatically_allowed(self) -> None:
        target = TargetResource(resource_type="service", resource_id="payments-service")
        req = ActionRequest(
            incident_id="INC-1",
            action_type=ActionType.ROLLBACK_DEPLOYMENT,
            target=target,
            environment="staging",
            rationale="Staging rollback",
        )
        decision = self.engine.evaluate(req)
        assert decision.decision == PolicyDecisionType.ALLOW
        assert decision.risk_class == RiskClass.LOW

    def test_production_rollback_requires_incident_commander(self) -> None:
        target = TargetResource(resource_type="service", resource_id="payments-service")
        req = ActionRequest(
            incident_id="INC-1",
            action_type=ActionType.ROLLBACK_DEPLOYMENT,
            target=target,
            environment="production",
            rationale="Prod rollback",
        )
        decision = self.engine.evaluate(req)
        assert decision.decision == PolicyDecisionType.REQUIRES_APPROVAL
        assert decision.required_role == ActorRole.INCIDENT_COMMANDER
        assert decision.risk_class == RiskClass.HIGH

        # Authorization checks
        op = ActorContext(actor_id="u1", role=ActorRole.OPERATOR)
        sre = ActorContext(actor_id="u2", role=ActorRole.SRE)
        ic = ActorContext(actor_id="u3", role=ActorRole.INCIDENT_COMMANDER)

        can_op, _ = self.engine.authorize_approval(req, decision, op)
        assert can_op is False

        can_sre, _ = self.engine.authorize_approval(req, decision, sre)
        assert can_sre is False

        can_ic, _ = self.engine.authorize_approval(req, decision, ic)
        assert can_ic is True
