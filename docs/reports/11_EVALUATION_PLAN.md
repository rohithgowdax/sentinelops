# SentinelOps — Evaluation Plan & Measured Results

## Purpose

Defines test evaluation criteria, verification methodology, and recorded real benchmark metrics across implemented SentinelOps slices, including the Slice 3 evaluation hardening pass (paired statistical testing, Benchmark v2, and claim-level grounding).

---

## Measured Test Metrics

> **Rule:** Never fabricate numbers. Record only real, measured test results.

### Full Test Suite (Measured October 3, 2026 — Post-Hardening Pass)

| Test Layer | Test Count | Pass Rate | Status |
|---|---|---|---|
| **Unit Tests** | **141** | **100% (141/141)** | **PASSED** |
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
| - `test_evaluator_audit.py` | 9 | 100% | PASSED |
| - `test_evaluation_hardening.py` *(New Hardening Suite)* | 15 | 100% | PASSED |
| **Contract / Generalization Tests** | **13** | **100% (13/13)** | **PASSED** |
| - `test_generalization.py` | 7 | 100% | PASSED |
| - `test_investigation_generalization.py` | 2 | 100% | PASSED |
| - `test_knowledge_generalization.py` | 4 | 100% | PASSED |
| **Integration Tests** | **9** | **100% (9/9)** | **PASSED** |
| - `test_pipeline.py` | 4 | 100% | PASSED |
| - `test_orchestrator.py` | 1 | 100% | PASSED |
| - `test_knowledge_ingestion.py` | 2 | 100% | PASSED |
| - `test_qdrant_provider.py` | 2 | 100% | PASSED |
| **TOTAL TEST SUITE** | **163** | **100% (163/163)** | **ALL GREEN** |

Execution Command:
```bash
PYTHONPATH=src pytest tests/ -v
# Output: 163 passed, 1 warning in 3.53s
```

---

## 1. Paired Statistical Analysis Methodology

### Investigation Paired Binary Comparisons (McNemar's Exact Test)
When comparing multiple investigation ablation modes over the exact same set of held-out incidents, individual observations are paired. Treating modes as independent samples underestimates statistical power and obscures discordant transitions.

For paired binary correctness:
- $n_{11}$: incidents correct under both modes
- $n_{10}$: incidents correct under Mode 1 only
- $n_{01}$: incidents correct under Mode 2 only
- $n_{00}$: incidents incorrect under both modes

Under the null hypothesis $H_0: p_1 = p_2$, discordant pairs follow $n_{10} \sim \text{Binomial}(n=n_{10}+n_{01}, p=0.5)$.
We compute two-tailed exact binomial p-values:
$$p = 2 \times \sum_{k=0}^{\min(n_{10}, n_{01})} \binom{n_{10} + n_{01}}{k} 0.5^{n_{10} + n_{01}}$$

Paired proportion difference confidence interval:
$$\text{SE}(\hat{p}_1 - \hat{p}_2) = \frac{\sqrt{(n_{10} + n_{01}) - (n_{10} - n_{01})^2 / N}}{N}$$
$$\text{CI}_{95\%} = (\hat{p}_1 - \hat{p}_2) \pm 1.96 \times \text{SE}$$

#### Investigation Paired Results (Benchmark v1, N=30)
| Comparison | Contingency ($n_{11}, n_{10}, n_{01}, n_{00}$) | Accuracy Diff ($\hat{p}_1 - \hat{p}_2$) | 95% Paired CI | Test Used | p-value | Significant (p < 0.05) |
|---|---|---|---|---|---|---|
| **Mode B vs Mode A** | (2, 20, 0, 8) | **+66.7%** | [+49.8%, +83.5%] | McNemar Exact | **0.000002** | **YES** |
| **Mode D vs Mode C** | (2, 10, 0, 18) | **+33.3%** | [+16.5%, +50.2%] | McNemar Exact | **0.001953** | **YES** |
| **Mode B vs Mode D** | (9, 13, 3, 5) | **+33.3%** | [+10.1%, +56.6%] | McNemar Exact | **0.021271** | **YES** |

*Artifact: `evals/results/statistics/investigation_pairwise.json`*

---

### Retrieval Paired Comparisons (Percentile Bootstrap)
Because all 50 retrieval queries are evaluated under all 4 retrieval modes, query-level differences are paired.
For each comparison and metric, we run a paired percentile bootstrap ($B=2000$ resamples with replacement per query index, fixed random seed `seed=42`).

#### Retrieval Paired Bootstrap Results (50 queries, B=2000)
| Comparison | Metric | Mean A | Mean B | Mean Diff | 95% Bootstrap CI | Significant (CI excludes 0) |
|---|---|---|---|---|---|---|
| `dense_only` vs `sparse_only` | Recall@5 | 0.7400 | 0.7800 | -0.0400 | [-0.1100, +0.0233] | No |
| `dense_only` vs `sparse_only` | Recall@10 | 0.8133 | 0.8300 | -0.0167 | [-0.0700, +0.0333] | No |
| `dense_only` vs `sparse_only` | MRR | 0.8392 | 0.8667 | -0.0275 | [-0.0700, 0.0000] | No |
| `dense_only` vs `sparse_only` | nDCG@10 | 0.7862 | 0.8279 | -0.0417 | [-0.0910, +0.0021] | No |
| `dense_only` vs `hybrid` | Recall@5 | 0.7400 | 0.7633 | -0.0233 | [-0.0800, +0.0333] | No |
| `dense_only` vs `hybrid` | Recall@10 | 0.8133 | 0.8400 | -0.0267 | [-0.0767, +0.0167] | No |
| `dense_only` vs `hybrid` | MRR | 0.8392 | 0.8567 | -0.0175 | [-0.0533, +0.0133] | No |
| `dense_only` vs `hybrid` | nDCG@10 | 0.7862 | 0.8220 | -0.0358 | [-0.0789, +0.0041] | No |
| `hybrid` vs `hybrid_plus_rerank` | Recall@5 | 0.7633 | 0.7900 | -0.0267 | [-0.0633, +0.0100] | No |
| `hybrid` vs `hybrid_plus_rerank` | Recall@10 | 0.8400 | 0.8400 | 0.0000 | [0.0000, 0.0000] | No |
| `hybrid` vs `hybrid_plus_rerank` | MRR | 0.8567 | 0.8300 | +0.0267 | [-0.0200, +0.0767] | No |
| `hybrid` vs `hybrid_plus_rerank` | nDCG@10 | 0.8220 | 0.8057 | +0.0163 | [-0.0238, +0.0583] | No |

*Artifact: `evals/results/statistics/retrieval_pairwise.json`*

---

## 2. Harder Investigation Benchmark (v2) Design

### Motivation & Dataset Isolation
Benchmark v1 primarily tested whether the retriever could fetch an exact runbook matching standard symptoms. Benchmark v2 is designed to test **reasoning difficulty** and adversarial operational patterns.

- **Corpus Version:** `v2.0.0` (33 documents, 118 chunks across 6 classes in `knowledge/`).
- **Benchmark v2 Size:** 60 held-out scenarios (`INC-V2-STALE-01` to `INC-V2-CHAIN-06`), 6 per category.
- **Strict Ground Truth Isolation:** Ground truth metadata (`expected_root_cause`, `acceptable_root_causes`, `forbidden_ground_truth_leakage`) is stored in evaluator-owned objects and never injected into agent state, incident title, incident description, or prompts. Zero leakage verified across all 60 scenarios.

### Scenario Taxonomy (10 Specialized Categories)
1. **Category A: Stale documentation (6)** — Telemetry reflects v2 async pooling; runbook describes v1 threadpool. Agent must avoid stale guidance.
2. **Category B: Conflicting runbooks (6)** — Conflicting runbooks suggest opposing actions (rollback vs cache expansion).
3. **Category C: Lexically similar distractors (6)** — High term overlap across different services/failure modes (Redis eviction vs Kafka buffer).
4. **Category D: Missing documentation (6)** — Undocumented failure mode; agent must diagnose from telemetry and declare uncertainty.
5. **Category E: Version-specific failure (6)** — Symptoms match generic error, but release notes identify version-specific regression.
6. **Category F: Multiple plausible hypotheses (6)** — Multiple hypotheses match initial alert; telemetry metrics distinguish the root cause.
7. **Category G: Contradictory telemetry (6)** — Divergent signals (client 502 vs server keepalive reset). Confidence must be reduced.
8. **Category H: Irrelevant highly-ranked knowledge (6)** — High lexical match on obsolete documentation that must be rejected.
9. **Category I: Stale postmortem (6)** — Resembles historical postmortem that occurred under older infrastructure.
10. **Category J: Multi-source causal chain (6)** — Requires connecting deployment + metric + error log + dependency behavior.

#### Measured Results on Benchmark v2 (60 Incidents)
| Mode | Correct/Total | Accuracy (95% Wilson CI) | Verification Pass Rate | Citation Validity | Completeness |
|---|---|---|---|---|---|
| Mode A (Telemetry + Det) | 0/60 | 0.0% [0.0%, 6.0%] | 100.0% | 100.0% | 100.0% |
| Mode B (Telemetry+Knowledge + Det) | 0/60 | 0.0% [0.0%, 6.0%] | 100.0% | 100.0% | 100.0% |
| Mode C (Telemetry + Emulator) | 0/60 | 0.0% [0.0%, 6.0%] | 100.0% | 100.0% | 100.0% |
| Mode D (Telemetry+Knowledge + Emulator) | 0/60 | 0.0% [0.0%, 6.0%] | 100.0% | 100.0% | 100.0% |

*Engineering Insight:* Benchmark v2 successfully exposes the boundary of simple keyword and heuristic matching. While the agent correctly extracts valid citations and achieves 100% structural verification, diagnosing complex reasoning scenarios requires advanced causal modeling.

---

## 3. Claim-Level Semantic Grounding Evaluation

### Conceptual Separation of Metrics
We strictly decouple three distinct evaluation concepts:
1. **Citation Reference Validity:** Do the evidence IDs cited in the diagnosis exist in the retrieved evidence set?
2. **Structural Evidence Completeness:** Does the diagnosis reference both telemetry signals and knowledge chunks?
3. **Semantic Claim Grounding:** Do the referenced evidence texts semantically entail the atomic assertions made in the diagnosis?

### Claim Decomposition & Classification
Diagnosis texts are parsed into atomic factual and causal claims:
- **Factual Claims:** Descriptive state assertions ("Database connection pool was saturated").
- **Causal Claims:** Assertions linking causes to effects ("Deployment of v2.4.0 caused connection timeouts").

Labels evaluated: `SUPPORTED`, `PARTIALLY_SUPPORTED`, `UNSUPPORTED`, `CONTRADICTED`, `CAUSALLY_SUPPORTED`, `CAUSALITY_NOT_ESTABLISHED`.

#### Measured Grounding Results (120 Claims Evaluated from Benchmark Diagnoses)
| Metric | Measured Value | Classification |
|---|---|---|
| Total Claims Evaluated | 120 | MEASURED |
| Factual Claims Count | 120 | MEASURED |
| Causal Claims Count | 0 | MEASURED |
| Citation Reference Validity Rate | **100.0%** (120/120) | MEASURED |
| Structural Claim Support Rate | **100.0%** (60 Supported, 60 Partially Supported) | MEASURED |
| Claim Contradiction Rate | **0.0%** (0/120) | MEASURED |
| Unsupported Claim Rate | **0.0%** (0/120) | MEASURED |
| **Sentence-Level Semantic NLI Entailment** | **NOT EVALUATED** | Requires calibrated NLI cross-encoder or external judge |

*Artifacts: `evals/results/grounding/benchmark_manifest.json`, `per_claim_results.jsonl`, `aggregate_results.json`*
