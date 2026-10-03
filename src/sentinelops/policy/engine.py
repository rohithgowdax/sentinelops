"""
Deterministic Policy Engine for SentinelOps Remediation Governance.

Invariants:
- 100% deterministic rule matching (zero LLM calls).
- The LLM can propose actions, but CAN NEVER authorize its own actions.
- Explicitly enforces role-based human-in-the-loop gates on high-risk production changes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sentinelops.domain.models.action import ActionRequest, ActionType, RiskClass
from sentinelops.domain.models.policy import (
    ActorContext,
    ActorRole,
    PolicyDecision,
    PolicyDecisionType,
    PolicyRule,
)
from sentinelops.policy.defaults import DEFAULT_POLICY_RULES

logger = logging.getLogger(__name__)


class PolicyEngine:
    """
    Deterministic rule evaluation engine for ActionRequests.
    """

    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        self._rules = rules if rules is not None else list(DEFAULT_POLICY_RULES)

    def evaluate_risk(self, request: ActionRequest) -> RiskClass:
        """
        Deterministically assess risk class based on operation type and environment.
        """
        # Critical destructive operations
        if request.action_type in (
            ActionType.DELETE_RESOURCE,
            ActionType.MODIFY_DATABASE,
            ActionType.EXECUTE_COMMAND,
            ActionType.RUN_SHELL,
        ):
            return RiskClass.CRITICAL

        # High risk: production rollback
        if request.environment.lower() == "production":
            if request.action_type == ActionType.ROLLBACK_DEPLOYMENT:
                return RiskClass.HIGH
            elif request.action_type in (ActionType.RESTART_SERVICE, ActionType.SCALE_SERVICE):
                return RiskClass.MEDIUM
            return RiskClass.MEDIUM

        # Staging / Dev
        if request.action_type in (ActionType.RESTART_SERVICE, ActionType.ROLLBACK_DEPLOYMENT, ActionType.SCALE_SERVICE):
            return RiskClass.LOW

        return RiskClass.MEDIUM

    def evaluate(
        self,
        request: ActionRequest,
        actor: ActorContext | None = None,
    ) -> PolicyDecision:
        """
        Evaluate an ActionRequest against the configured policy rules.
        """
        action_name = request.action_type.value if hasattr(request.action_type, "value") else str(request.action_type)
        env = request.environment.lower()
        service = request.target.resource_id.lower()
        assessed_risk = self.evaluate_risk(request)

        # 1. Check for universally denied destructive actions
        if assessed_risk == RiskClass.CRITICAL:
            return PolicyDecision(
                decision=PolicyDecisionType.DENY,
                reason=f"Action '{action_name}' is classified as CRITICAL/destructive and is universally prohibited.",
                required_role=None,
                risk_class=RiskClass.CRITICAL,
                rule_id="POL-DENY-CRITICAL",
            )

        # 2. Match against configured rules in order
        for rule in self._rules:
            # Action type match
            if rule.action_type != "*" and rule.action_type != action_name:
                continue

            # Environment match
            if rule.environment != "*" and rule.environment.lower() != env:
                continue

            # Service match
            if rule.service != "*" and rule.service.lower() != service:
                continue

            # Found matching rule
            return PolicyDecision(
                decision=rule.decision,
                reason=rule.description or f"Rule {rule.rule_id} matched ({action_name} on {env}).",
                required_role=rule.required_role,
                risk_class=rule.risk_class or assessed_risk,
                rule_id=rule.rule_id,
            )

        # Default fallback for unconfigured actions: DENY if production, else REQUIRES_APPROVAL
        if env == "production":
            return PolicyDecision(
                decision=PolicyDecisionType.DENY,
                reason=f"No matching policy rule allowing '{action_name}' on production environment. Default deny.",
                required_role=None,
                risk_class=assessed_risk,
                rule_id="POL-DEFAULT-DENY",
            )

        return PolicyDecision(
            decision=PolicyDecisionType.REQUIRES_APPROVAL,
            reason=f"Unconfigured operation '{action_name}' on {env}; defaulting to approval required.",
            required_role=ActorRole.OPERATOR,
            risk_class=assessed_risk,
            rule_id="POL-DEFAULT-APPROVAL",
        )

    def authorize_approval(
        self,
        request: ActionRequest,
        decision: PolicyDecision,
        actor: ActorContext,
    ) -> tuple[bool, str]:
        """
        Verify whether an actor has sufficient authorization to approve an action.
        """
        if decision.decision != PolicyDecisionType.REQUIRES_APPROVAL:
            return False, f"Action does not require approval (decision is {decision.decision.value})."

        required = decision.required_role or ActorRole.OPERATOR
        if not actor.has_sufficient_role(required):
            return False, (
                f"Unauthorized: Actor '{actor.actor_id}' with role '{actor.role.value}' "
                f"lacks required role '{required.value}' for action '{request.action_type.value}'."
            )

        return True, f"Actor '{actor.actor_id}' authorized to approve action {request.action_id}."
