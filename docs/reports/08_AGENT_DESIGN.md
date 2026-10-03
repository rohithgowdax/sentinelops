# SentinelOps — AI Investigation Agent Design (Slice 2)

## Purpose

This document specifies the architecture, state contracts, node responsibilities, routing logic, and architectural invariants of the **SentinelOps AI Investigation Agent** implemented in Slice 2.

The agent consumes canonical `incident.created` events from Redis Stream `sentinel:incidents` and produces a structured, evidence-grounded root cause diagnosis.

---

## Architectural Principles & Invariants

1. **Incident Input is Canonical:** The agent consumes the canonical `Incident` domain model. It never inspects `source_provider` or alters investigation behavior based on telemetry origin.
2. **Strict Capability Decoupling:** Agent nodes never execute raw SQL (`psycopg`, `SELECT`) or connect directly to Redis. All operational queries are mediated through the `TelemetryEvidenceProvider` protocol.
3. **Structured Typed Contracts:** Nodes exchange structured Pydantic models (`InvestigationPlan`, `InvestigationEvidence`, `Hypothesis`, `Diagnosis`, `VerificationResult`) across an explicit `InvestigationState` TypedDict. Free-form text prompts and untyped dictionaries are prohibited between nodes.
4. **Evidence Citation Invariant:** Every `Diagnosis` must cite at least one valid, existing `evidence_id` in `supporting_evidence`. Invented or hallucinated evidence IDs are strictly prohibited and audited by the verification gate.
5. **Deterministic Bounded Execution:** The investigation cycle contains a conditional loop with a hard ceiling (`max_iterations = 3`). Infinite looping is structurally impossible.
6. **No Production Action:** In Slice 2, the agent is strictly diagnostic. Remediations are recorded only as non-executable advisory recommendations (`recommended_actions`).

---

## LangGraph Topology

```
START
  │
  ▼
incident_intake
  │
  ▼
build_investigation_plan
  │
  ▼
collect_evidence ◄──────────────────────────────┐
  │                                             │
  ▼                                             │
analyze_evidence                                │
  │                                             │
  ▼                                             │
diagnose                                        │
  │                                             │
  ▼                                             │
verify_diagnosis                                │
  │                                             │
  ├─── [is_verified == False AND iter < 3] ─────┘
  │
  └─── [is_verified == True OR iter >= 3]
  │
  ▼
finalize
  │
  ▼
END
```

---

## State Schema (`sentinelops.agent.state.InvestigationState`)

```python
class InvestigationState(TypedDict):
    incident: Incident
    investigation_plan: InvestigationPlan | None
    current_step: int
    iteration: int
    max_iterations: int
    evidence: list[InvestigationEvidence]
    hypotheses: list[Hypothesis]
    selected_hypothesis: Hypothesis | None
    diagnosis: Diagnosis | None
    confidence: float
    verification_result: VerificationResult | None
    status: InvestigationStatus
    errors: list[str]
    tool_calls_summary: list[dict[str, Any]]
    start_time_iso: str
    final_result: InvestigationResult | None
```

---

## Node Responsibilities

### 1. `incident_intake` (`agent/nodes/intake.py`)
- **Type:** Synchronous validator
- **Responsibilities:**
  - Validates inbound canonical `Incident`.
  - Initializes investigation clock (`start_time_iso`).
  - Sets lifecycle status to `INVESTIGATING`.
  - Sets baseline `iteration = 0`.
- **Invariant:** Zero diagnostic speculation occurs in this node.

### 2. `build_investigation_plan` (`agent/nodes/planner.py`)
- **Type:** Async reasoning node (`make_planner_node(llm_provider)`)
- **Responsibilities:**
  - Evaluates incident trigger type, affected service, and firing rule.
  - Generates an ordered sequence of `InvestigationStep` items citing generic capabilities (`telemetry`, `baseline`, `trigger_context`).
  - Records rationale explaining the planned investigation approach.

### 3. `collect_evidence` (`agent/nodes/collector.py`)
- **Type:** Async tool execution node (`make_collector_node(evidence_provider)`)
- **Responsibilities:**
  - Increments `iteration` counter.
  - Executes planned queries against `TelemetryEvidenceProvider`.
  - Translates capability query outputs into immutable `InvestigationEvidence` records (`E01`, `E02`, ...).
  - Appends tool calls to `tool_calls_summary` for auditability.
  - Catches non-fatal capability errors without terminating the workflow.

### 4. `analyze_evidence` (`agent/nodes/analyzer.py`)
- **Type:** Async correlation node (`make_analyzer_node(llm_provider)`)
- **Responsibilities:**
  - Correlates quantitative observations across all collected evidence items.
  - Formulates candidate failure `Hypothesis` items.
  - Every hypothesis references specific `supporting_evidence_ids`.
  - Selects top candidate hypothesis based on confidence.

### 5. `diagnose` (`agent/nodes/diagnoser.py`)
- **Type:** Async synthesis node (`make_diagnoser_node(llm_provider)`)
- **Responsibilities:**
  - Synthesizes the selected hypothesis and supporting evidence into a definitive `Diagnosis`.
  - Mandates inclusion of `supporting_evidence` IDs.
  - Populates advisory `recommended_actions` (non-executable).

### 6. `verify_diagnosis` (`agent/nodes/verifier.py`)
- **Type:** Async audit gate (`make_verifier_node(llm_provider)`)
- **Responsibilities:**
  - Evaluates whether cited evidence IDs exist and mathematically support the diagnosis.
  - Checks for contradictions or sample size deficiencies.
  - Produces `VerificationResult(is_verified=bool, confidence=float, reason=str)`.

### 7. Conditional Router (`route_after_verification`)
- **Logic:**
  ```python
  if verification.is_verified:
      return "finalize"
  if iteration < max_iterations:
      return "collect_evidence"
  return "finalize"
  ```

### 8. `finalize` (`agent/nodes/finalizer.py`)
- **Type:** Synchronous terminal node
- **Responsibilities:**
  - Sets final status: `DIAGNOSED` if verified, or `INSUFFICIENT_EVIDENCE` if max iterations reached without verification.
  - Computes total wall-clock duration (`duration_seconds`).
  - Packages complete investigation history into immutable `InvestigationResult`.

---

## Durable State Checkpointing

The compiled graph uses LangGraph's checkpointer mechanism (`MemorySaver` in development/testing, pluggable to PostgreSQL/Redis for production):
- Each investigation run is bound to `config = {"configurable": {"thread_id": incident.incident_id}}`.
- Graph state is persisted after every node execution.
- Enables post-investigation inspection, auditing, and resumption.

---

## LLM Provider Abstraction (`capabilities/llm/`)

To guarantee determinism, CI testability, and zero external network/billing dependencies:
- Defined `LLMProvider` protocol covering `generate_plan`, `analyze_hypotheses`, `generate_diagnosis`, and `verify_diagnosis`.
- Implemented `DeterministicLLMProvider`:
  - Parses quantitative metric anomalies, baseline deviations, and elevation ratios.
  - Guarantees strict evidence citation without hallucination.
  - Easily swappable for Anthropic Claude, OpenAI, or Google Gemini providers behind the same protocol.

---

## Verification & Test Results

The AI Investigation Agent is verified by:
1. **Unit Tests (`tests/unit/test_investigation_state.py`, `test_investigation_nodes.py`, `test_evidence_provider.py`):** 20 tests verifying models, validation, and isolated node execution.
2. **Graph Execution Tests (`tests/unit/test_investigation_graph.py`):** 4 tests verifying happy-path flow, re-investigation loops, max-iteration termination, and state checkpointing.
3. **Generalization Contract Tests (`tests/contract/test_investigation_generalization.py`):** Proves AST-level zero provider branching and identical diagnosis semantics across OTel and custom JSON.
4. **End-to-End Pipeline Integration Tests (`tests/integration/test_orchestrator.py`):** Full loop from Redis incident event to LangGraph, PostgreSQL persistence, and REST API retrieval.
