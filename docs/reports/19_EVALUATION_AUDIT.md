# SentinelOps — Slice 3 Evaluation Audit & Benchmark Hardening Report

**Date:** October 3, 2026  
**Auditor:** SentinelOps Core Engineering & AI Evaluation Pass  
**Status:** Audit Complete & Hardened  

---

## 1. Executive Summary

An audit and hardening pass was conducted on the SentinelOps Slice 3 evaluation and benchmarking infrastructure. The purpose was to independently verify whether reported retrieval and investigation benchmark metrics were technically defensible, reproducible, and mathematically sound.

The audit identified three major defects in the previous reporting:
1. **Unbounded nDCG@10 (reported as 1.6118 – 1.6842):** Caused by aggregating chunk-level relevance gains against an unnormalized theoretical single-document ideal, violating the standard $0.0 \le \text{nDCG} \le 1.0$ bound.
2. **Dense / Sparse / Hybrid Parity Bug:** `dense_only`, `sparse_only`, and `hybrid` retrieval modes reported identical scores (0.7400 Recall@5) because `QdrantKnowledgeProvider` never fitted BM25 document frequencies when freshly instantiated, causing sparse scores to evaluate to zero and resulting in identical dense rankings.
3. **Misleading "Real-Model" Classification & Latency (17–22 ms):** The reported "Real LLM" latency did not measure calls to an external proprietary API, but rather local CPU inference of an offline semantic emulator when no API key was provided.

All three defects have been remediated, verified with automated regression tests, and audited against live Qdrant and synthetic incident workloads.

---

## 2. Initial Concerns

Prior to this pass, the following reported figures raised engineering concerns:
- **nDCG > 1.0:** In standard Information Retrieval literature, Normalized Discounted Cumulative Gain cannot exceed 1.0. A score of 1.6118 indicated a normalization or indexing error.
- **Identical metrics across distinct retrieval strategies:** Dense cosine search and BM25 sparse search should exhibit distinct recall and ranking characteristics. Reporting identical 0.7400 Recall@5 and 0.8392 MRR across both indicated that one search path was non-functional.
- **Sub-25 ms LLM latency:** External cloud LLM APIs (e.g. Anthropic Claude, OpenAI GPT-4, Google Gemini) typically take 800–3000 ms per turn. Reporting 17–22 ms without clarifying offline emulation was misleading.

---

## 3. Findings Summary Table

| Issue ID | Component | Observed Behavior | Root Cause | Severity | Resolution |
|---|---|---|---|---|---|
| **AUDIT-01** | Retrieval Evaluator (`run_retrieval_eval.py`) | nDCG@10 reported as 1.6118 – 1.6842 | Chunk-level relevance accumulated without deduplication; DCG divided by $IDCG$ computed on unique documents | **High** (Invalid Metric) | Deduplicate retrieved chunks to document level preserving earliest rank; strictly enforce $[0.0, 1.0]$ bounds |
| **AUDIT-02** | Qdrant Provider (`qdrant_provider.py`) | Dense, sparse, and hybrid modes yielded identical 0.7400 Recall@5 | Fresh provider instances had `_doc_count = 0` and empty BM25 stats, returning 0.0 sparse scores | **High** (False Parity) | Implemented `_ensure_bm25_fit()` to fit BM25 dynamically on indexed chunks; isolated candidate retrieval paths |
| **AUDIT-03** | Real LLM Provider (`real_provider.py`) | 17–22 ms reported as "Real LLM" latency | `RealLLMProvider` operates as an offline semantic emulator when no API key is present; local CPU time was reported as LLM API latency | **Medium** (Misleading Taxonomy) | Formally classify provider as `offline_semantic_emulator`; report local CPU time honestly; record external tokens and costs as `NOT AVAILABLE` |
| **AUDIT-04** | Statistical Reporting | Point estimates reported without sample variance or uncertainty | Small sample size ($n=30$ incidents) yielded point estimates vulnerable to noise | **Low** (Incomplete Reporting) | Added Wilson score 95% confidence intervals to all investigation accuracy metrics |
| **AUDIT-05** | Benchmark Isolation | Need to guarantee held-out incidents do not leak into runbook knowledge | Benchmark incident IDs and expected root causes must never appear in agent context | **Low** (Risk Mitigation) | Added automated test verifying zero leakage of benchmark incident IDs in knowledge base; verified ground truth root causes are excluded from agent prompts |

---

## 4. Detailed Root Cause Analysis & Corrections

### 4.1 nDCG Implementation & Boundedness
- **Observed:**
  `compute_ndcg_at_k` was computing:
  $$\text{DCG@k} = \sum_{i=1}^k \frac{\text{rel}(r_i)}{\log_2(i + 1)}$$
  where multiple retrieved chunks from the same relevant document were each awarded a binary gain of 1.0. When 3 chunks from `DOC-PG-01` appeared in the top 5, each contributed gain. Meanwhile, $\text{IDCG@k}$ was calculated based on the number of unique relevant documents (here, 1 document $\implies \text{IDCG} = 1.0$). Consequently:
  $$\text{nDCG@10} = \frac{1.6118}{1.0} = 1.6118 > 1.0$$
- **Correction:**
  In standard IR evaluation, queries with binary document-level relevance labels evaluate relevance per *document*. The evaluator was updated to deduplicate chunks at the document level, recording a document's relevant gain at its earliest retrieved rank. If no relevant document is retrieved, $\text{DCG} = 0.0$; if the relevant document is at rank 1, $\text{DCG} = \text{IDCG} = 1.0 \implies \text{nDCG} = 1.0$.

### 4.2 Dense / Sparse / Hybrid Parity Bug
- **Observed:**
  When `evals/run_retrieval_eval.py` instantiated a new `QdrantKnowledgeProvider` pointing to an existing Qdrant collection, Qdrant held the dense vectors and payloads. However, the in-memory BM25 index attributes (`_doc_count`, `_doc_freqs`) were empty. When `_search_sparse` was invoked, `_compute_bm25_score` returned 0.0 for every document. As a result, Python's `list.sort(key=..., reverse=True)` retained the initial order (or dense candidate order), rendering sparse and hybrid search identical to dense search.
- **Correction:**
  Added `_ensure_bm25_fit()`, which dynamically scans existing indexed points in Qdrant and fits BM25 document frequencies on the first sparse or hybrid query. Furthermore, distinct candidate generation paths were implemented so sparse candidates originate purely from token matches, yielding true search diversity.

### 4.3 "Real-Model" Average Latency & Provider Classification
- **Observed:**
  `RealLLMProvider` was created with a dual pathway: if an API key (e.g. `ANTHROPIC_API_KEY`) is present, it calls the external API; if absent, it falls back to a deterministic semantic emulator using regex pattern matching and structural synthesis. The benchmark ran without an API key, executing the offline emulator in 17–22 ms, but the report labeled this as "Real LLM".
- **Correction:**
  The provider now explicitly exposes its operating mode: `offline_semantic_emulator` vs. `external_api`. Latency is explicitly documented as local CPU execution time. Token counts, token latency, and financial costs are marked as `NOT AVAILABLE` rather than fabricated.

---

## 5. Corrected Benchmark Results

### 5.1 Retrieval Benchmark (50 Queries, Live Qdrant)

Measured on macOS (Apple Silicon), live Qdrant container, 50 queries across 6 incident classes:

| Retrieval Mode | Recall@5 | Recall@10 | MRR | nDCG@10 | Latency (Mean) | Latency (p50) | Latency (p95) |
|---|---|---|---|---|---|---|---|
| `dense_only` | 0.7400 | 0.8133 | 0.8392 | 0.7862 | 2.5 ms | 2.2 ms | 3.5 ms |
| `sparse_only` | 0.7800 | 0.8300 | 0.8667 | 0.8279 | 5.2 ms | 5.1 ms | 6.4 ms |
| `hybrid` | 0.7633 | 0.8400 | 0.8567 | 0.8220 | 8.2 ms | 7.9 ms | 11.3 ms |
| `hybrid_plus_rerank` | **0.7900** | **0.8400** | 0.8300 | 0.8057 | 8.4 ms | 8.4 ms | 10.4 ms |

#### Candidate Overlap Analysis (Top-5 Retrieved Documents):
- **Dense ∩ Sparse Overlap:** **52.00%** (Confirms distinct retrieval characteristics)
- **Dense ∩ Hybrid Overlap:** **70.00%**
- **Sparse ∩ Hybrid Overlap:** **74.00%**

---

### 5.2 Investigation Ablation Benchmark (30 Held-Out Incidents)

Evaluated across 30 held-out incidents (`INC-DEP-01` through `INC-DEP-30`):

| Mode | Provider Configuration | Accuracy (Correct/Total) | 95% Wilson CI | Verification Pass Rate | Citation Validity | Evidence Completeness | Latency (p50 / p95) | External Tokens & Cost |
|---|---|---|---|---|---|---|---|---|
| **A** | Telemetry Only + Deterministic | 6.7% (2/30) | [1.8%, 21.3%] | 100.0% | 100.0% | 100.0% | 0.005s / 0.018s | *NOT AVAILABLE* |
| **B** | Telemetry + Knowledge + Deterministic | **73.3% (22/30)** | [55.5%, 85.8%] | 100.0% | 100.0% | 100.0% | 0.020s / 0.026s | *NOT AVAILABLE* |
| **C** | Telemetry Only + Offline Emulator | 6.7% (2/30) | [1.8%, 21.3%] | 100.0% | 100.0% | 100.0% | 0.005s / 0.009s | *NOT AVAILABLE* |
| **D** | Telemetry + Knowledge + Offline Emulator | **40.0% (12/30)** | [24.6%, 57.7%] | 100.0% | 100.0% | 100.0% | 0.019s / 0.027s | *NOT AVAILABLE* |

---

## 6. Evaluator Architecture & Hardening Summary

The hardened evaluator infrastructure consists of:
1. **`src/sentinelops/evals/run_retrieval_eval.py`**:
   - Executes retrieval against live or in-memory vector stores.
   - Evaluates standard bounded Recall@k, MRR, and document-level nDCG@k.
   - Emits structured JSON/JSONL artifacts.
2. **`src/sentinelops/evals/run_llm_eval.py`**:
   - Runs investigation ablations across held-out incidents.
   - Computes Wilson 95% confidence intervals for small sample proportions.
   - Strictly enforces citation checking and evidence completeness.
   - Classifies LLM providers as deterministic, offline emulator, or external API.
3. **`tests/unit/test_evaluator_audit.py`**:
   - 9 regression tests verifying evaluator correctness:
     - Mathematical bounds of nDCG ($0.0 \le \text{nDCG} \le 1.0$).
     - Rank discounting behavior.
     - Dense vs. sparse ranking divergence.
     - Dynamic BM25 fitting on fresh provider instances.
     - Reciprocal rank fusion ordering.
     - Reranker metadata adjustments.
     - Offline emulator accounting and honest labeling.
     - Rejection of hallucinated citation IDs.
     - Benchmark dataset isolation and zero leakages.

---

## 7. Exact Commands to Reproduce All Evaluations

### 7.1 Run Full Test Suite (148 tests)
```bash
cd /Users/rohithgowda/Desktop/Project/sentinelops
PYTHONPATH=src pytest tests/ -v
```

### 7.2 Run Evaluator Audit Regression Suite (9 tests)
```bash
cd /Users/rohithgowda/Desktop/Project/sentinelops
PYTHONPATH=src pytest tests/unit/test_evaluator_audit.py -v
```

### 7.3 Reproduce Retrieval Benchmark (50 queries)
```bash
cd /Users/rohithgowda/Desktop/Project/sentinelops
PYTHONPATH=src python -m sentinelops.evals.run_retrieval_eval
```
*Artifacts generated in `evals/results/retrieval/`.*

### 7.4 Reproduce Investigation Ablation Benchmark (30 incidents)
```bash
cd /Users/rohithgowda/Desktop/Project/sentinelops
PYTHONPATH=src python -m sentinelops.evals.run_llm_eval
```
*Artifacts generated in `evals/results/investigation/`.*

---

## 8. Remaining Limitations & Next Steps

1. **Claim-Level NLI Entailment:** The current evaluation checks whether retrieved chunk IDs are referenced in the diagnosis citations. It does *not* run a secondary NLI model or LLM judge to verify sentence-level semantic entailment. This remains classified as **NOT EVALUATED**.
2. **External Cloud LLM API Evaluation:** Live benchmarking against external LLM providers (e.g. Claude 3.5 Sonnet, GPT-4o) requires configured API credentials and network egress. When run in CI or offline sandbox environments, the system accurately falls back to the `offline_semantic_emulator`. Real-world token latencies (TTFT, inter-token time) and API cost tracking will be evaluated when live credentials are supplied.
3. **Corpus Scale:** The knowledge base currently contains 24 curated technical operational documents (70 chunks). While representative of core microservice failure modes, evaluating retrieval at enterprise scale (> 100,000 documents) will require dedicated distributed benchmarking.
