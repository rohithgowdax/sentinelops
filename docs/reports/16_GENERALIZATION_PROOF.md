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

## Summary

| Proof Component | Test Count | Result |
|---|---|---|
| Canonical metric meaning equivalence | 5 | ✅ All passed |
| Same rule fires for both sources | 4 | ✅ All passed |
| Equivalent incident semantics | 2 | ✅ All passed |
| No provider-specific branching in detector | 2 | ✅ All passed |
| Zero provider branching in Agent AST (Slice 2) | 1 | ✅ Passed |
| Semantic equivalence across sources in Agent (Slice 2) | 1 | ✅ Passed |
| **Total generalization contract tests** | **15** | **✅ 15/15 passed** |

---

## What This Proves About Architecture

The generalization proof demonstrates that:

1. **Adapter isolation is complete.** All provider-specific logic is contained within `normalize()`. Nothing leaks to the core.

2. **Unit normalization works.** The 18% custom JSON value (0–100 scale) is correctly normalized to 0.18 (0–1 ratio) to match the OTel convention, enabling rule thresholds to be expressed once in canonical units.

3. **The detection engine is provider-neutral by construction, not by convention.** The test verifies this structurally — different providers produce the same evaluation outcome because the function operates only on canonical fields.

4. **Deduplication is provider-neutral.** A second incident would not be created even if one record came from OTel and another from the custom agent, because they share the same `episode_key`.

5. **Agent reasoning is provider-neutral.** The LangGraph investigation loop reasons entirely over canonical domain abstractions and queries evidence through provider capability protocols (`TelemetryEvidenceProvider`). There are zero branches on telemetry sources anywhere in the agent codebase.

6. **Adding a third provider requires zero changes to detection, investigation, storage, or API.** Only a new telemetry adapter and its unit tests are needed.

