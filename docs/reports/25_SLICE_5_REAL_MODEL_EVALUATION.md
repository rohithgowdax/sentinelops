# Slice 5: External LLM & MCP Performance Evaluation

**Status:** IMPLEMENTED & BENCHMARKED  
**Date:** October 2026  
**Honesty Policy:** Explicit status taxonomy (`MEASURED`, `SIMULATED`, `NOT RUN`)  

---

## 1. Evaluation Modalities & Status Taxonomy

To avoid metric inflation and maintain absolute reproducibility, SentinelOps strictly partitions evaluation runs into clear categories:

1. **`MEASURED`:** Deterministic tests, unit tests, security suites, and local in-memory/MCP benchmarks run against actual code and verifiable test cases.
2. **`SIMULATED`:** Offline semantic emulator runs using local heuristic and keyword embeddings.
3. **`NOT RUN`:** External cloud API invocations (e.g. OpenAI, Anthropic, Bedrock) when corresponding API keys or active internet endpoints are unconfigured.

---

## 2. External LLM Evaluation Runner (`run_external_llm_eval.py`)

The evaluation runner supports three execution modes:
* `--mode deterministic`: Evaluates against `DeterministicLLMProvider`.
* `--mode offline_semantic_emulator`: Evaluates against `OfflineSemanticEmulatorLLMProvider`.
* `--mode external_api`: Invokes live external model endpoints (Anthropic, OpenAI, or Bedrock).

### Status Manifest Output:
When run without live API keys:
```json
{
  "benchmark_name": "Slice 5 External LLM Evaluation",
  "status": "NOT RUN",
  "reason": "EXTERNAL_LLM_API_KEY environment variable is not set. External API calls were omitted to ensure honest reporting.",
  "timestamp": "2026-10-04T20:55:04.298064",
  "samples_evaluated": 0,
  "accuracy": null
}
```

---

## 3. MCP Performance Overhead Benchmark (`run_mcp_perf_eval.py`)

A formal comparative benchmark was executed measuring latency for direct method invocation vs. local in-process MCP JSON-RPC protocol handling across 50 iterations:

> [!NOTE]
> This benchmark measures **local in-process MCP dispatch overhead** (serialization, schema validation, context mapping). It does **not** simulate or claim production WAN/HTTP network transit times.

```json
{
  "benchmark_name": "MCP Tool Call Performance Benchmark",
  "total_iterations": 50,
  "results": {
    "query_metrics": {
      "direct_avg_ms": 0.00041,
      "mcp_avg_ms": 0.02231,
      "overhead_ms": 0.02190
    },
    "search_knowledge": {
      "direct_avg_ms": 0.20379,
      "mcp_avg_ms": 0.22173,
      "overhead_ms": 0.01794
    },
    "get_service_health": {
      "direct_avg_ms": 0.00038,
      "mcp_avg_ms": 0.00940,
      "overhead_ms": 0.00902
    }
  }
}
```

### Analysis:
- The maximum protocol overhead observed is **0.0219 ms** (21.9 microseconds).
- Serialization, schema validation, and context propagation have virtually zero impact on operational response times in-process.
