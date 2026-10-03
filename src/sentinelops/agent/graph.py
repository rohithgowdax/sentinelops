"""
LangGraph Investigation StateGraph Assembly for SentinelOps.

Graph Topology:
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
collect_evidence  ◄───────────────┐
  │                               │
  ▼                               │
analyze_evidence                  │ (insufficient / loop back)
  │                               │
  ▼                               │
diagnose                          │
  │                               │
  ▼                               │
verify_diagnosis ─────────────────┘
  │
  ▼ (sufficient / max iterations)
finalize
  │
  ▼
END
```

Durable State:
Uses a LangGraph checkpointer (default: `MemorySaver`) with `incident_id` as the thread ID.
"""
from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from sentinelops.agent.nodes.analyzer import make_analyzer_node
from sentinelops.agent.nodes.collector import make_collector_node
from sentinelops.agent.nodes.diagnoser import make_diagnoser_node
from sentinelops.agent.nodes.finalizer import finalize
from sentinelops.agent.nodes.intake import incident_intake
from sentinelops.agent.nodes.planner import make_planner_node
from sentinelops.agent.nodes.verifier import make_verifier_node, route_after_verification
from sentinelops.agent.state import InvestigationState
from sentinelops.domain.contracts.protocols import (
    KnowledgeProvider,
    LLMProvider,
    TelemetryEvidenceProvider,
)



def create_investigation_graph(
    evidence_provider: TelemetryEvidenceProvider,
    llm_provider: LLMProvider,
    knowledge_provider: KnowledgeProvider | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """
    Construct, wire, and compile the SentinelOps incident investigation graph.

    Args:
        evidence_provider: Telemetry evidence capability implementation.
        llm_provider: LLM reasoning provider implementation.
        knowledge_provider: Optional knowledge provider for runbook/postmortem retrieval.
        checkpointer: Optional checkpointer instance (default: `MemorySaver`).

    Returns:
        Compiled `CompiledStateGraph` ready for execution.
    """
    # 1. Instantiate state graph builder with InvestigationState
    builder = StateGraph(InvestigationState)

    # 2. Add nodes with injected capability dependencies
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

    # 3. Add deterministic sequential edges
    builder.add_edge(START, "incident_intake")
    builder.add_edge("incident_intake", "build_investigation_plan")
    builder.add_edge("build_investigation_plan", "collect_evidence")
    builder.add_edge("collect_evidence", "analyze_evidence")
    builder.add_edge("analyze_evidence", "diagnose")
    builder.add_edge("diagnose", "verify_diagnosis")

    # 4. Add conditional edge for verification gate and bounded loop
    builder.add_conditional_edges(
        "verify_diagnosis",
        route_after_verification,
        {
            "collect_evidence": "collect_evidence",
            "finalize": "finalize",
        },
    )

    # 5. Add terminal edge
    builder.add_edge("finalize", END)

    # 6. Default checkpointer for durable state
    saver = checkpointer if checkpointer is not None else MemorySaver()

    # 7. Compile graph
    return builder.compile(checkpointer=saver)
