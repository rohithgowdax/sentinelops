"""
Default Declarative Remediation Policy Rules for SentinelOps.

Defines deterministic rules governing permitted, approval-gated, and denied operations.
"""
from __future__ import annotations

from sentinelops.domain.models.action import ActionType, RiskClass
from sentinelops.domain.models.policy import (
    ActorRole,
    PolicyDecisionType,
    PolicyRule,
)

DEFAULT_POLICY_RULES: list[PolicyRule] = [
    # 1. Deny destructive or arbitrary shell operations universally across all environments
    PolicyRule(
        rule_id="POL-DENY-DESTRUCTIVE-01",
        action_type=ActionType.DELETE_RESOURCE.value,
        environment="*",
        decision=PolicyDecisionType.DENY,
        risk_class=RiskClass.CRITICAL,
        description="Destructive deletion of resources is strictly forbidden via autonomous agents.",
    ),
    PolicyRule(
        rule_id="POL-DENY-DESTRUCTIVE-02",
        action_type=ActionType.MODIFY_DATABASE.value,
        environment="*",
        decision=PolicyDecisionType.DENY,
        risk_class=RiskClass.CRITICAL,
        description="Direct database modification is strictly prohibited.",
    ),
    PolicyRule(
        rule_id="POL-DENY-DESTRUCTIVE-03",
        action_type=ActionType.EXECUTE_COMMAND.value,
        environment="*",
        decision=PolicyDecisionType.DENY,
        risk_class=RiskClass.CRITICAL,
        description="Arbitrary command execution is strictly prohibited.",
    ),
    PolicyRule(
        rule_id="POL-DENY-DESTRUCTIVE-04",
        action_type=ActionType.RUN_SHELL.value,
        environment="*",
        decision=PolicyDecisionType.DENY,
        risk_class=RiskClass.CRITICAL,
        description="Arbitrary shell execution is strictly prohibited.",
    ),
    # 2. Non-production (staging/dev) policies
    PolicyRule(
        rule_id="POL-ALLOW-STAGING-RESTART",
        action_type=ActionType.RESTART_SERVICE.value,
        environment="staging",
        decision=PolicyDecisionType.ALLOW,
        risk_class=RiskClass.LOW,
        description="Automatic service restart permitted in staging environments.",
    ),
    PolicyRule(
        rule_id="POL-ALLOW-STAGING-ROLLBACK",
        action_type=ActionType.ROLLBACK_DEPLOYMENT.value,
        environment="staging",
        decision=PolicyDecisionType.ALLOW,
        risk_class=RiskClass.LOW,
        description="Automatic rollback permitted in staging environments.",
    ),
    PolicyRule(
        rule_id="POL-ALLOW-STAGING-SCALE",
        action_type=ActionType.SCALE_SERVICE.value,
        environment="staging",
        decision=PolicyDecisionType.ALLOW,
        risk_class=RiskClass.LOW,
        description="Automatic scaling permitted in staging environments.",
    ),
    # 3. Production policies (Approval-gated)
    PolicyRule(
        rule_id="POL-PROD-ROLLBACK-APPROVAL",
        action_type=ActionType.ROLLBACK_DEPLOYMENT.value,
        environment="production",
        decision=PolicyDecisionType.REQUIRES_APPROVAL,
        required_role=ActorRole.INCIDENT_COMMANDER,
        risk_class=RiskClass.HIGH,
        description="Production deployment rollback is high risk; requires Incident Commander approval.",
    ),
    PolicyRule(
        rule_id="POL-PROD-RESTART-APPROVAL",
        action_type=ActionType.RESTART_SERVICE.value,
        environment="production",
        decision=PolicyDecisionType.REQUIRES_APPROVAL,
        required_role=ActorRole.SRE,
        risk_class=RiskClass.MEDIUM,
        description="Production service restart requires SRE or higher approval.",
    ),
    PolicyRule(
        rule_id="POL-PROD-SCALE-APPROVAL",
        action_type=ActionType.SCALE_SERVICE.value,
        environment="production",
        decision=PolicyDecisionType.REQUIRES_APPROVAL,
        required_role=ActorRole.SRE,
        risk_class=RiskClass.MEDIUM,
        description="Production service scaling requires SRE or higher approval.",
    ),
]
