# SentinelOps — Generalization Proof

## Claim

> "Two different external telemetry formats can enter through different adapters, become the same canonical model, and use the exact same detection/core pipeline."

This document records the evidence that this architectural claim is true in slice 1.

---

## Proof Structure

The proof has four parts, each backed by automated tests in `tests/contract/test_generalization.py`.

### Part 1: Canonical Metric Meaning is Equivalent

**Signal:** `payments-service` error rate of 18%.

**Adapter A input (OTel-like JSON):**
```json
{
  "resource": {
    "service.name": "payments-service",
    "deployment.environment": "production"
  },
  "metric": {
    "name": "http.error_rate",
    "value": 0.18,
    "unit": "ratio"
  },
  "timestamp": "2026-10-01T14:37:12Z"
}
```

**Adapter B input (Custom JSON):**
```json
{
  "svc": "payments-service",
  "env": "production",
  "metric_name": "err_pct",
  "metric_value": 18.0,
  "unit": "percent",
  "time": "2026-10-01T14:37:12Z"
}
```

**After normalization — Canonical record A:**
```
resource.service_name = "payments-service"
resource.environment  = "production"
metric.name           = "http.error_rate"
metric.value          = 0.18
metric.unit           = "ratio"
signal_type           = "metric"
source.provider       = "otel"         ← different
```

**After normalization — Canonical record B:**
```
resource.service_name = "payments-service"
resource.environment  = "production"
metric.name           = "http.error_rate"
metric.value          = 0.18            ← 18.0% → 0.18 ratio (normalized)
metric.unit           = "ratio"
signal_type           = "metric"
source.provider       = "custom_json"  ← different
```

**Assertions verified by tests:**
- `test_canonical_service_name_equivalent`: ✅ PASSED
- `test_canonical_metric_name_equivalent`: ✅ PASSED
- `test_canonical_metric_value_equivalent`: ✅ PASSED
- `test_canonical_environment_equivalent`: ✅ PASSED
- `test_canonical_signal_type_equivalent`: ✅ PASSED

---

### Part 2: The Same Detection Rule Fires for Both

**Rule applied:**
```yaml
rule_id: rule-001-elevated-service-errors
metric: http.error_rate
operator: gt
threshold: 0.10
aggregation: latest
```

**With Record A (OTel-produced):** `evaluate_rule(rule, [record_a], ...)` → `fired=True`, `observed_value=0.18`

**With Record B (custom JSON-produced):** `evaluate_rule(rule, [record_b], ...)` → `fired=True`, `observed_value=0.18`

**With below-threshold values from either adapter:** → `fired=False`

**Assertions verified by tests:**
- `test_same_rule_fires_for_otel_record`: ✅ PASSED
- `test_same_rule_fires_for_custom_record`: ✅ PASSED
- `test_rule_does_not_fire_below_threshold_otel`: ✅ PASSED
- `test_rule_does_not_fire_below_threshold_custom`: ✅ PASSED

---

### Part 3: Resulting Incidents Have Equivalent Semantic Fields

Both adapter sources, when they cause a detection rule to fire, produce an `EvaluationResult` with the same:
- `episode_key` = `"rule-001-elevated-service-errors::payments-service::production"`
- `observed_value` ≈ 0.18
- `fired` = True

This means both would produce an `Incident` with the same:
- `episode_key` (deduplication key)
- `service_name`
- `trigger_rule_id`
- `severity`

**Assertions verified by tests:**
- `test_episode_key_equivalent_for_both_sources`: ✅ PASSED
- `test_observed_values_approximately_equal`: ✅ PASSED

---

### Part 4: The Detector Contains No Provider-Specific Branching

**Method:** Structural inspection via test.

The `evaluate_rule()` function signature:
```python
def evaluate_rule(
    rule: DetectionRule,
    records: list[TelemetryRecord],
    service_name: str,
    environment: str | None,
) -> EvaluationResult:
```

The function accesses only:
- `record.metric.name` — canonical
- `record.metric.value` — canonical
- `rule.*` — pure rule fields

It **never accesses** `record.source.provider` or `record.source.integration_id`.

The test `test_detector_does_not_inspect_provider` verifies:
1. `rec_a.source.provider != rec_b.source.provider` (providers are demonstrably different)
2. `res_a.fired == res_b.fired` (outcomes are identical despite different providers)
3. `res_a.episode_key == res_b.episode_key` (deduplication is provider-neutral)

Additionally, `test_mixed_source_batch_fires` proves that a batch containing records from **both** adapters is evaluated correctly — the detector processes the mixed batch identically to a single-source batch.

**Assertions verified by tests:**
- `test_detector_does_not_inspect_provider`: ✅ PASSED
- `test_mixed_source_batch_fires`: ✅ PASSED

---

### Part 5: AI Investigation Loop Generalization & Zero-Branching Proof (Slice 2)

**Claim:**
The LangGraph AI investigation loop operates purely on canonical domain models (`Incident`, `InvestigationPlan`, `InvestigationEvidence`, `Hypothesis`, `Diagnosis`, `VerificationResult`) and contains zero conditional branching on telemetry provider sources. Incidents triggered by different telemetry providers result in identical, evidence-grounded diagnosis semantics.

**Proof 1: Static AST Zero-Branching Analysis**
Automated test `test_zero_provider_branching_in_agent_ast` parses Python Abstract Syntax Trees across all agent files:
- `src/sentinelops/agent/nodes/*.py` (`intake.py`, `planner.py`, `collector.py`, `analyzer.py`, `diagnoser.py`, `verifier.py`, `finalizer.py`)
- `src/sentinelops/agent/graph.py`
- `src/sentinelops/agent/state.py`
- `src/sentinelops/agent/prompts.py`

It verifies that no AST comparison node compares against prohibited provider literals (`"otel"`, `"custom_json"`, `"prometheus"`, `"datadog"`, `"cloudwatch"`).

**Proof 2: Cross-Source Semantic Diagnosis Equivalence**
Automated test `test_semantic_equivalence_across_sources`:
1. Constructs an incident `INC-OTEL-001` via `OtelLikeAdapter`.
2. Constructs an incident `INC-CUSTOM-001` via `CustomJsonAdapter`.
3. Runs both through the identical compiled LangGraph investigation graph (`create_investigation_graph()`).
4. Asserts that outputs match exactly:
   - `res_otel.status == res_custom.status == InvestigationStatus.DIAGNOSED`
   - `res_otel.confidence == res_custom.confidence` (e.g. 0.85)
   - `res_otel.diagnosis.root_cause == res_custom.diagnosis.root_cause`
   - `len(res_otel.investigation_steps) == len(res_custom.investigation_steps)`
   - `res_otel.diagnosis.recommended_actions == res_custom.diagnosis.recommended_actions`

**Assertions verified by tests:**
- `test_zero_provider_branching_in_agent_ast`: ✅ PASSED
- `test_semantic_equivalence_across_sources`: ✅ PASSED

---

## Part 6: Knowledge Capability Generalization Proof (Slice 3)

The knowledge generalization tests in `tests/contract/test_knowledge_generalization.py` prove that the incident investigation agent remains completely decoupled from vector database technologies and gracefully handles retrieval outages.

### Proof 1: Static AST Zero-Vector DB Coupling Analysis
Automated test `test_zero_vector_db_imports_in_agent_ast` parses Python Abstract Syntax Trees across all agent files:
- `src/sentinelops/agent/nodes/*.py`
- `src/sentinelops/agent/graph.py`
- `src/sentinelops/agent/state.py`
- `src/sentinelops/agent/prompts.py`

It verifies that no AST import node imports vendor vector packages:
- `"qdrant_client"`, `"chromadb"`, `"pymilvus"`, `"openai"`, `"anthropic"`, `"google.generativeai"`

Result: **0 vendor imports detected**.

### Proof 2: Capability Protocol Conformance
Automated test `test_knowledge_provider_protocol_conformance` verifies that both implementations:
- `InMemoryKnowledgeProvider`
- `QdrantKnowledgeProvider`
satisfy the `KnowledgeProvider` Protocol at the class structure level via `issubclass()`.

### Proof 3: Cross-Provider Canonical Result Equivalence
Automated test `test_equivalent_canonical_results_across_providers`:
1. Ingests identical test knowledge chunks into `InMemoryKnowledgeProvider` and `QdrantKnowledgeProvider` (`:memory:`).
2. Executes identical `KnowledgeQuery(query="restart leaking worker pods connection slots", mode=RetrievalMode.DENSE_ONLY)`.
3. Proves that both return identical canonical `KnowledgeResult` structures:
   - `im_res.document_id == qd_res.document_id == "rb-db-001"`
   - `im_res.chunk_id == qd_res.chunk_id == "CHK-EQUIV-01"`
   - `im_res.document_type == qd_res.document_type == DocumentType.RUNBOOK`
   - `im_res.title == qd_res.title == "Postgres Runbook"`
   - `im_res.section == qd_res.section == "Resolution"`
   - `im_res.service == qd_res.service == "payments-service"`
   - `im_res.content == qd_res.content`

### Proof 4: Graceful Degradation on Knowledge Failure
Automated test `test_graceful_fallback_when_knowledge_unavailable`:
1. Configures a `KnowledgeProvider` mock that raises `KnowledgeUnavailableError("Connection to vector DB timed out")`.
2. Runs a full LangGraph investigation for a live incident.
3. Proves that:
   - The agent does not crash or exit with error.
   - The investigation completes with `status == InvestigationStatus.DIAGNOSED`.
   - The state records `knowledge_available = False` and logs the retrieval error.
   - Diagnosis is successfully grounded in live operational telemetry.

**Assertions verified by tests:**
- `test_zero_vector_db_imports_in_agent_ast`: ✅ PASSED
- `test_knowledge_provider_protocol_conformance`: ✅ PASSED
- `test_equivalent_canonical_results_across_providers`: ✅ PASSED
- `test_graceful_fallback_when_knowledge_unavailable`: ✅ PASSED

---

## 5. Slice 4 Proof: Controlled Remediation Generalization

### Proof 1: ActionProvider Protocol Conformance
Automated test `test_protocol_conformance` verifies that both implementations:
- `MockServiceDeploymentProvider`
- `MockContainerProvider`
satisfy the `ActionProvider` Protocol at the class structure level.

### Proof 2: Zero Provider Branching in Remediation AST
Automated test `test_zero_provider_branching_in_remediation_ast` parses the AST of `remediation_planner.py`, `policy_evaluator.py`, `action_executor.py`, and `remediation_verifier.py`. Confirms zero comparison or branching on provider names (`"mock_service_deployment_provider"`, `"mock_container_provider"`, `"kubernetes"`, `"ecs"`, `"aws"`, `"docker"`).

### Proof 3: Cross-Provider Canonical Action Execution
Automated test `test_canonical_action_execution_across_providers`:
1. Constructs an identical canonical `ActionRequest` (`action_type=RESTART_SERVICE`).
2. Validates and executes on both `MockServiceDeploymentProvider` and `MockContainerProvider`.
3. Proves both return `ActionStatus.SUCCEEDED` with the same `action_id`.

### Proof 4: Idempotency Enforced Across Providers
Automated test `test_idempotency_enforced_across_providers`:
1. Submits duplicate action executions to both providers.
2. Proves both providers return cached identical `ActionResult` objects.

### Proof 5: LangGraph Flow Equivalence Across Providers
Automated test `test_langgraph_flow_equivalence_across_providers`:
1. Executes the complete investigation and remediation LangGraph flow.
2. Confirms both providers drive the incident to `status == InvestigationStatus.RESOLVED` and `remediation_status == "resolved"`.

---

## Summary

| Proof Component | Test Count | Result |
|---|---|---|
| Canonical metric meaning equivalence | 5 | ✅ All passed |
| Same rule fires for both sources | 4 | ✅ All passed |
| Equivalent incident semantics | 2 | ✅ All passed |
| No provider-specific branching in detector | 2 | ✅ All passed |
| Zero provider branching in Agent AST (Slice 2) | 1 | ✅ Passed |
| Semantic equivalence across sources in Agent (Slice 2) | 1 | ✅ Passed |
| Zero vector DB imports in Agent AST (Slice 3) | 1 | ✅ Passed |
| KnowledgeProvider protocol conformance (Slice 3) | 1 | ✅ Passed |
| Equivalent canonical knowledge results across stores (Slice 3) | 1 | ✅ Passed |
| Graceful degradation on knowledge outage (Slice 3) | 1 | ✅ Passed |
| ActionProvider protocol conformance (Slice 4) | 1 | ✅ Passed |
| Zero provider branching in Remediation AST (Slice 4) | 1 | ✅ Passed |
| Cross-provider canonical action execution (Slice 4) | 1 | ✅ Passed |
| Idempotency enforced across providers (Slice 4) | 1 | ✅ Passed |
| LangGraph flow equivalence across providers (Slice 4) | 1 | ✅ Passed |
| **Total generalization contract tests** | **24** | **✅ 24/24 passed** |

---

## What This Proves About Architecture

The generalization proofs across Slices 1, 2, 3, and 4 demonstrate that:

1. **Adapter isolation is complete.** All telemetry provider-specific logic is contained within `normalize()`.
2. **Detection engine is provider-neutral by construction.** Operates exclusively on canonical types.
3. **Agent reasoning is decoupled from storage and telemetry vendors.** Queries operational context solely via `TelemetryEvidenceProvider`.
4. **Agent reasoning is decoupled from vector databases.** Communicates with organizational knowledge solely via `KnowledgeProvider`.
5. **Remediation planning and policy are cloud-agnostic.** Operates exclusively on canonical `ActionRequest` and `ActionResult` domain models.
6. **Action providers are interchangeable.** Heterogeneous deployment managers and container orchestrators plug in seamlessly behind `ActionProvider` with zero changes to the LangGraph agent.


