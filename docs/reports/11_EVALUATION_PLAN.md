# SentinelOps — Evaluation Plan & Measured Results

## Purpose

Defines test evaluation criteria, verification methodology, and recorded real benchmark metrics across implemented SentinelOps slices, including the hardened Slice 3 retrieval and investigation evaluation suites.

---

## Measured Test Metrics

> **Rule:** Never fabricate numbers. Record only real, measured test results.

### Full Test Suite (Measured October 3, 2026 — Post-Audit Hardening)

| Test Layer | Test Count | Pass Rate | Status |
|---|---|---|---|
| **Unit Tests** | **126** | **100% (126/126)** | **PASSED** |
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
| - `test_knowledge_models.py` | 5 | 100% | PASSED |
| - `test_in_memory_knowledge.py` | 6 | 100% | PASSED |
| - `test_hybrid_retrieval.py` | 4 | 100% | PASSED |
| - `test_reranker.py` | 4 | 100% | PASSED |
| - `test_prompt_injection.py` | 4 | 100% | PASSED |
| - `test_evaluator_audit.py` *(New Audit Suite)* | 9 | 100% | PASSED |
| **Contract / Generalization Tests** | **13** | **100% (13/13)** | **PASSED** |
| - `test_generalization.py` | 7 | 100% | PASSED |
| - `test_investigation_generalization.py` | 2 | 100% | PASSED |
| - `test_knowledge_generalization.py` | 4 | 100% | PASSED |
| **Integration Tests** | **9** | **100% (9/9)** | **PASSED** |
| - `test_pipeline.py` | 4 | 100% | PASSED |
| - `test_orchestrator.py` | 1 | 100% | PASSED |
| - `test_knowledge_ingestion.py` | 2 | 100% | PASSED |
| - `test_qdrant_provider.py` | 2 | 100% | PASSED |
| **TOTAL TEST SUITE** | **148** | **100% (148/148)** | **ALL GREEN** |

Execution Command:
```bash
PYTHONPATH=src pytest tests/ -v
# Output: 148 passed, 1 warning in 3.30s
```

---

## Slice 3 Retrieval Evaluation Methodology

### Dataset & Query Suite
- **Corpus:** 24 technical operational documents (70 chunked passages) indexed in Qdrant (HNSW index, 384-dimensional dense vectors) and BM25 sparse index.
- **Query Set:** 50 realistic operational incident queries across 6 incident classes (connection pool exhaustion, JVM memory leaks, downstream cascading timeouts, bad configuration deployments, disk volume saturation, and cache stampedes).
- **Ground Truth:** Deterministic mapping of each query to its corresponding authoritative source document ID (`doc_id`).

### Retrieval Modes Evaluated
1. `dense_only`: Cosine vector similarity search via Qdrant.
2. `sparse_only`: Inverted index BM25 search over tokenized knowledge corpus.
3. `hybrid`: Reciprocal Rank Fusion ($k=60$) combining dense and sparse candidate lists.
4. `hybrid_plus_rerank`: RRF candidates reranked using `CrossFeatureReranker` (service match, actionable section priority, title keyword overlap, document diversification).

### Scoring Metrics & Mathematical Formulas
- **Recall@k:** $\frac{|\{d \in \text{retrieved}_{1..k} : d \in \text{relevant}\}|}{|\text{relevant}|}$
- **MRR (Mean Reciprocal Rank):** $\frac{1}{|Q|} \sum_{q \in Q} \frac{1}{\text{rank}_q(\text{first\_relevant})}$
- **nDCG@k (Normalized Discounted Cumulative Gain):** Evaluated at the *document level* by deduplicating retrieved chunks belonging to the same document (retaining earliest rank).
  $$\text{DCG@k} = \sum_{i=1}^k \frac{\text{rel}_i}{\log_2(i + 1)}$$
  $$\text{IDCG@k} = \sum_{i=1}^{\min(k, |\text{relevant}|)} \frac{1}{\log_2(i + 1)}$$
  $$\text{nDCG@k} = \frac{\text{DCG@k}}{\text{IDCG@k}} \in [0.0, 1.0]$$
- **Latency Percentiles:** Recorded wall-clock query duration: mean, 50th percentile (median), 95th percentile.

### Retrieval Benchmark Measured Results (50 queries, live Qdrant)

| Mode | Recall@5 | Recall@10 | MRR | nDCG@10 | Latency (Mean) | Latency (p50) | Latency (p95) |
|---|---|---|---|---|---|---|---|
| `dense_only` | 0.7400 | 0.8133 | 0.8392 | 0.7862 | 2.5 ms | 2.2 ms | 3.5 ms |
| `sparse_only` | 0.7800 | 0.8300 | 0.8667 | 0.8279 | 5.2 ms | 5.1 ms | 6.4 ms |
| `hybrid` | 0.7633 | 0.8400 | 0.8567 | 0.8220 | 8.2 ms | 7.9 ms | 11.3 ms |
| `hybrid_plus_rerank` | **0.7900** | **0.8400** | 0.8300 | 0.8057 | 8.4 ms | 8.4 ms | 10.4 ms |

- **Top-5 Candidate Overlap:**
  - Dense ∩ Sparse: 52.00%
  - Dense ∩ Hybrid: 70.00%
  - Sparse ∩ Hybrid: 74.00%

---

## Slice 3 Investigation Ablation Methodology

### Dataset & Scenario Isolation
- **Evaluation Set:** 30 held-out synthetic incident scenarios (`INC-DEP-01` through `INC-DEP-30`) covering connection exhaustion, memory leak, network saturation, disk full, CPU saturation, and deployment rollback triggers.
- **Strict Isolation Guarantee:** None of the held-out incident scenario IDs appear anywhere in the indexed runbook knowledge base. The ground-truth root cause label (`expected_root_cause_concept`) is used solely for offline evaluation scoring and is never injected into agent state, graph context, or prompts.

### Modes Evaluated
- **Mode A (Telemetry + Deterministic):** Operational metrics only, rule-based reasoning engine.
- **Mode B (Telemetry + Knowledge + Deterministic):** Metrics + hybrid RRF knowledge retrieval, rule-based reasoning engine.
- **Mode C (Telemetry + Semantic Emulator):** Metrics only, local semantic inference provider.
- **Mode D (Telemetry + Knowledge + Semantic Emulator):** Metrics + hybrid RRF knowledge retrieval, local semantic inference provider.

### Scoring Metrics & Confidence Intervals
- **Root Cause Accuracy:** Proportion of diagnoses whose identified root cause contains the target ground-truth concept keywords.
- **Confidence Intervals:** 95% Wilson score confidence interval calculated as:
  $$\frac{\hat{p} + \frac{z^2}{2n} \pm z \sqrt{\frac{\hat{p}(1-\hat{p})}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}} \quad (z=1.96, n=30)$$
- **Diagnosis Verification Pass Rate:** Proportion of diagnoses satisfying the `verify_diagnosis` node threshold.
- **Citation Validity Rate:** Proportion of cited chunk IDs that actually exist in the retrieved knowledge set.
- **Evidence Completeness Rate:** Proportion of diagnoses that cite both telemetry observations and knowledge chunks.
- **Claim-Level NLI Entailment:** Explicitly marked as **NOT EVALUATED** (no human judge or calibrated NLI cross-encoder was deployed).

### Investigation Ablation Measured Results (30 held-out incidents)

| Mode | Accuracy (Passed/Total) | 95% Wilson CI | Verification Pass Rate | Citation Validity | Completeness | Latency (p50 / p95) | Token Latency & Cost |
|---|---|---|---|---|---|---|---|
| **A: Telemetry + Det** | 6.7% (2/30) | [1.8%, 21.3%] | 100.0% | 100.0% | 100.0% | 0.005s / 0.018s | *NOT AVAILABLE* (deterministic) |
| **B: Telemetry+Knowledge + Det** | **73.3% (22/30)** | [55.5%, 85.8%] | 100.0% | 100.0% | 100.0% | 0.020s / 0.026s | *NOT AVAILABLE* (deterministic) |
| **C: Telemetry + Emulator** | 6.7% (2/30) | [1.8%, 21.3%] | 100.0% | 100.0% | 100.0% | 0.005s / 0.009s | *NOT AVAILABLE* (offline emulator) |
| **D: Telemetry+Knowledge + Emulator** | **40.0% (12/30)** | [24.6%, 57.7%] | 100.0% | 100.0% | 100.0% | 0.019s / 0.027s | *NOT AVAILABLE* (offline emulator) |

---

## Machine-Readable Benchmark Artifacts

All benchmark executions emit complete structured manifests and per-sample results:

```text
evals/results/
├── retrieval/
│   ├── benchmark_manifest.json     # Configuration, corpus metadata, timestamp, environment
│   ├── per_query_results.jsonl      # Query text, target doc, retrieved chunks, per-query metrics
│   └── aggregate_results.json       # Mode-level Recall, MRR, nDCG, latency percentiles, overlaps
└── investigation/
    ├── benchmark_manifest.json     # Mode list, incident count, provider configurations
    ├── per_incident_results.jsonl   # Incident ID, matched concept, cited IDs, pass/fail status
    └── aggregate_results.json       # Accuracies, Wilson CIs, verification rates, CPU latencies
```

---

## Evaluator Audit Regression Tests

Located in `tests/unit/test_evaluator_audit.py`:
1. `test_ndcg_bounded_between_zero_and_one`: Verifies $\text{nDCG@k} \in [0.0, 1.0]$ across perfect, duplicate, and empty rankings.
2. `test_ndcg_penalizes_lower_rank_documents`: Verifies DCG discounts late-ranked relevant documents.
3. `test_dense_and_sparse_return_different_rankings`: Verifies dense and sparse rankings are distinct (no false parity).
4. `test_bm25_fits_dynamically_on_fresh_provider`: Verifies `_ensure_bm25_fit` populates IDF frequencies on un-indexed providers.
5. `test_hybrid_fusion_combines_dense_and_sparse_correctly`: Verifies RRF produces expected rank order.
6. `test_reranker_adjusts_ranking`: Verifies metadata scoring elevates matching services and actionable sections.
7. `test_real_llm_provider_offline_accounting`: Verifies provider flags itself as `offline_semantic_emulator` and latency is local CPU time.
8. `test_citation_validity_rejects_hallucinated_ids`: Verifies fabricated citations fail validation.
9. `test_held_out_benchmark_isolation`: Verifies held-out incident IDs do not leak into runbook knowledge documents.
