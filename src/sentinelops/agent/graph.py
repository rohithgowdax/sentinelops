r"""
LangGraph Investigation & Controlled Remediation StateGraph Assembly for SentinelOps.

Graph Topology (Slice 4):
```text
START
  │
  ▼
incident_intake
  │
  ▼
build_investigation_plan
  │
  ▼
collect_evidence  ◄──────────────────────────────────────┐
  │                                                      │
  ▼                                                      │
analyze_evidence                                         │
  │                                                      │
  ▼                                                      │
diagnose                                                 │
  │                                                      │
  ▼                                                      │
verify_diagnosis ────────────────────────────────────────┤ (insufficient / loop back)
  │                                                      │
  ├── (unverified & max iter) ──► finalize ──► END       │
  │                                                      │
  ▼ (verified)                                           │
plan_remediation                                         │
  │                                                      │
  ▼                                                      │
evaluate_policy                                          │
  │                                                      │
  ├── DENY ─────────────────────► finalize_denied ──► END│
  │                                                      │
  ├── REQUIRES_APPROVAL ──► await_approval (interrupt)   │
  │                              │                       │
  │                   [resume with approval]             │
  │                              ▼                       │
  └── ALLOW ──────────────► execute_action               │
                                 │                       │
                                 ▼                       │
                          verify_remediation             │
                            /          \                 │
                       RECOVERED     NOT_RECOVERED       │
                          │                 │            │
                          ▼                 ▼            │
                  finalize_resolved  (retry < max) ──────┘
                          │                 │ (retry >= max)
                          ▼                 ▼
                         END         finalize_failed ──► END
```
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from sentinelops.agent.nodes.action_executor import (
    make_action_executor_node,
    make_await_approval_node,
    route_after_approval,
)
from sentinelops.agent.nodes.analyzer import make_analyzer_node
from sentinelops.agent.nodes.collector import make_collector_node
from sentinelops.agent.nodes.diagnoser import make_diagnoser_node
from sentinelops.agent.nodes.finalizer import finalize
from sentinelops.agent.nodes.intake import incident_intake
from sentinelops.agent.nodes.planner import make_planner_node
from sentinelops.agent.nodes.policy_evaluator import (
    make_policy_evaluator_node,
    route_after_policy,
)
from sentinelops.agent.nodes.remediation_planner import make_remediation_planner_node
from sentinelops.agent.nodes.remediation_verifier import (
    make_finalize_denied_node,
    make_finalize_failed_node,
    make_finalize_resolved_node,
    make_remediation_verifier_node,
    route_after_remediation_verification,
)
from sentinelops.agent.nodes.verifier import make_verifier_node, route_after_verification
from sentinelops.agent.state import InvestigationState
from sentinelops.approval.service import ApprovalService
from sentinelops.audit.service import AuditService
from sentinelops.capabilities.actions.protocol import ActionProvider
from sentinelops.domain.contracts.protocols import (
    KnowledgeProvider,
    LLMProvider,
    TelemetryEvidenceProvider,
)
from sentinelops.policy.engine import PolicyEngine

logger = logging.getLogger(__name__)


def create_investigation_graph(
    evidence_provider: TelemetryEvidenceProvider,
    llm_provider: LLMProvider,
    knowledge_provider: KnowledgeProvider | None = None,
    action_provider: ActionProvider | None = None,
    policy_engine: PolicyEngine | None = None,
    approval_service: ApprovalService | None = None,
    audit_service: AuditService | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """
    Construct, wire, and compile the SentinelOps incident investigation and controlled remediation graph.
    """
    builder = StateGraph(InvestigationState)

    # 1. Core Investigation Nodes
    builder.add_node("incident_intake", incident_intake)
    builder.add_node("build_investigation_plan", make_planner_node(llm_provider))
    builder.add_node(
        "collect_evidence",
        make_collector_node(
            evidence_provider=evidence_provider,
            knowledge_provider=knowledge_provider,
            llm_provider=llm_provider,
        ),
    )
    builder.add_node("analyze_evidence", make_analyzer_node(llm_provider))
    builder.add_node("diagnose", make_diagnoser_node(llm_provider))
    builder.add_node("verify_diagnosis", make_verifier_node(llm_provider))
    builder.add_node("finalize", finalize)

    # Sequential edges for investigation phase
    builder.add_edge(START, "incident_intake")
    builder.add_edge("incident_intake", "build_investigation_plan")
    builder.add_edge("build_investigation_plan", "collect_evidence")
    builder.add_edge("collect_evidence", "analyze_evidence")
    builder.add_edge("analyze_evidence", "diagnose")
    builder.add_edge("diagnose", "verify_diagnosis")

    # 2. Remediation Phase Nodes (if action_provider is configured)
    if action_provider is not None:
        p_engine = policy_engine or PolicyEngine()
        builder.add_node("plan_remediation", make_remediation_planner_node(audit_service=audit_service))
        builder.add_node(
            "evaluate_policy",
            make_policy_evaluator_node(
                policy_engine=p_engine,
                approval_service=approval_service,
                audit_service=audit_service,
            ),
        )
        builder.add_node(
            "await_approval",
            make_await_approval_node(
                approval_service=approval_service,
                audit_service=audit_service,
            ),
        )
        builder.add_node(
            "execute_action",
            make_action_executor_node(
                action_provider=action_provider,
                approval_service=approval_service,
                audit_service=audit_service,
            ),
        )
        builder.add_node(
            "verify_remediation",
            make_remediation_verifier_node(
                evidence_provider=evidence_provider,
                action_provider=action_provider,
                audit_service=audit_service,
            ),
        )
        builder.add_node("finalize_resolved", make_finalize_resolved_node(audit_service=audit_service))
        builder.add_node("finalize_denied", make_finalize_denied_node(audit_service=audit_service))
        builder.add_node("finalize_failed", make_finalize_failed_node(audit_service=audit_service))

        # Dynamic router after diagnosis verification
        def route_after_diagnosis(state: InvestigationState) -> str:
            ver = state.get("verification_result")
            it = state.get("iteration", 0)
            max_it = state.get("max_iterations", 3)

            if ver and ver.is_verified:
                return "plan_remediation"
            if it < max_it:
                return "collect_evidence"
            return "finalize"

        builder.add_conditional_edges(
            "verify_diagnosis",
            route_after_diagnosis,
            {
                "plan_remediation": "plan_remediation",
                "collect_evidence": "collect_evidence",
                "finalize": "finalize",
            },
        )

        # Edges for remediation flow
        builder.add_edge("plan_remediation", "evaluate_policy")
        builder.add_conditional_edges(
            "evaluate_policy",
            route_after_policy,
            {
                "execute_action": "execute_action",
                "await_approval": "await_approval",
                "finalize_denied": "finalize_denied",
            },
        )
        builder.add_conditional_edges(
            "await_approval",
            route_after_approval,
            {
                "execute_action": "execute_action",
                "finalize_denied": "finalize_denied",
            },
        )
        builder.add_edge("execute_action", "verify_remediation")
        builder.add_conditional_edges(
            "verify_remediation",
            route_after_remediation_verification,
            {
                "finalize_resolved": "finalize_resolved",
                "collect_evidence": "collect_evidence",
                "finalize_failed": "finalize_failed",
            },
        )
        builder.add_edge("finalize_resolved", END)
        builder.add_edge("finalize_denied", END)
        builder.add_edge("finalize_failed", END)

    else:
        # Backward-compatible Slice 2/3 investigation routing
        builder.add_conditional_edges(
            "verify_diagnosis",
            route_after_verification,
            {
                "collect_evidence": "collect_evidence",
                "finalize": "finalize",
            },
        )

    builder.add_edge("finalize", END)

    saver = checkpointer if checkpointer is not None else MemorySaver()
    return builder.compile(checkpointer=saver)
