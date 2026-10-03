# SentinelOps — Evaluation Plan & Measured Results

## Purpose

Defines test evaluation criteria, verification methodology, and recorded real benchmark metrics across implemented SentinelOps slices.

---

## Measured Test Metrics

> **Rule:** Never fabricate numbers. Record only real, measured test results.

### Slice 1 & Slice 2 Test Suite (Measured October 3, 2026)

| Test Layer | Test Count | Pass Rate | Status |
|---|---|---|---|
| **Unit Tests** | 103 | 100% (103/103) | **PASSED** |
| - `test_adapter_otel.py` | 13 | 100% | PASSED |
| - `test_adapter_custom.py` | 13 | 100% | PASSED |
| - `test_detection_engine.py` | 22 | 100% | PASSED |
| - `test_detection_rules.py` | 5 | 100% | PASSED |
| - `test_evidence_provider.py` | 5 | 100% | PASSED |
| - `test_incidents.py` | 9 | 100% | PASSED |
| - `test_investigation_graph.py` | 4 | 100% | PASSED |
| - `test_investigation_nodes.py` | 8 | 100% | PASSED |
| - `test_investigation_state.py` | 7 | 100% | PASSED |
| - `test_telemetry_models.py` | 7 | 100% | PASSED |
| **Contract / Generalization Tests** | 9 | 100% (9/9) | **PASSED** |
| - `test_generalization.py` | 7 | 100% | PASSED |
| - `test_investigation_generalization.py` | 2 | 100% | PASSED |
| **Integration Tests** | 5 | 100% (5/5) | **PASSED** |
| - `test_pipeline.py` | 4 | 100% | PASSED |
| - `test_orchestrator.py` | 1 | 100% | PASSED |
| **TOTAL TEST SUITE** | **117** | **100% (117/117)** | **ALL GREEN** |

Execution Command:
```bash
PYTHONPATH=src pytest tests/ -v
# Output: 117 passed in 2.67s
```

---

## Slice 2 Evaluation Criteria

| Evaluation Target | Verification Criteria | Measured Result |
|---|---|---|
| **Canonical Intake** | Graph consumes canonical `Incident` without provider inspection | Verified (`test_semantic_equivalence_across_sources`) |
| **AST Provider Neutrality** | Zero branching on `provider` names in agent nodes, state, prompts | Verified via AST scan (`test_zero_provider_branching_in_agent_ast`) |
| **Strict Evidence Citation** | 100% of generated diagnoses cite valid, existing evidence IDs | Verified across unit, graph, and integration runs |
| **Loop Bounding** | Hard termination at `max_iterations = 3` with `INSUFFICIENT_EVIDENCE` | Verified (`test_max_iteration_termination_insufficient_evidence`) |
| **Durable Checkpointing** | State checkpoint retrievable per `incident_id` thread ID | Verified (`test_state_checkpointing_per_thread_id`) |
| **Stream Acknowledgment** | `sentinel:incidents` message ACKed ONLY after Postgres save | Verified (`test_full_investigation_pipeline_and_api`) |
| **REST API Serving** | `GET /incidents/{id}/investigation` returns valid 200 / 404 | Verified (`test_full_investigation_pipeline_and_api`) |

---

## NOT YET MEASURED (Out of Scope for Slices 1 & 2)

- Microsecond telemetry ingestion throughput under sustained load (> 10,000 EPS)
- Remediation MTTR (Remediation is out of scope until Slice 4)
- LLM token latency on external proprietary APIs (Anthropic/OpenAI) — testing used `DeterministicLLMProvider`
