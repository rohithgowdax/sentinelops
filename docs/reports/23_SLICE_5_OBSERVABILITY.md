# Slice 5: End-to-End Observability

**Status:** IMPLEMENTED & VERIFIED  
**Date:** October 2026  
**Standards Compliance:** W3C TraceContext, OpenTelemetry Semantic Conventions  

---

## 1. Overview & Architecture

SentinelOps provides full lifecycle observability across all agent workflows, tool calls, policy evaluations, and external integrations without leaking sensitive infrastructure credentials or chain-of-thought tokens.

```text
Investigation / Remediation Workflow
                 │
      ┌──────────┴──────────┐
      ▼                     ▼
Tracer (W3C Tracing)   MetricsCollector (Lifecycle Timers & Counters)
      │                     │
      ▼                     ▼
OpenTelemetry Span     OTel Standard Metric
      └──────────┬──────────┘
                 ▼
       OpenTelemetryJsonExporter
```

---

## 2. Distributed Tracing (`Tracer` & `Span`)

* **W3C TraceContext Compliance:**
  * `trace_id`: 32-character lowercase hex string (`uuid4().hex`)
  * `span_id`: 16-character lowercase hex string (`uuid4().hex[:16]`)
  * `traceparent` propagation header: `00-{trace_id}-{span_id}-01`
* **Nested Context Handling:** Async and sync context managers support hierarchical span parenting with accurate start/end timestamps.
* **Semantic Attributes:** Follows standard OpenTelemetry semantic conventions for LLM, database, and HTTP calls (`gen_ai.system`, `gen_ai.request.model`, `mcp.server.name`, `mcp.tool.name`, `policy.decision`).

---

## 3. Data Sanitization & Secret Redaction

To prevent sensitive credentials and unconstrained internal reasoning logs from leaking into distributed tracing backends, the tracer automatically passes all span attributes through recursive sanitization (`sanitize_attributes`):

* **Secret Redaction:** High-entropy tokens, AWS keys (`AKIA...`), Bearer tokens, passwords, and private keys are matched via regex and replaced with `[REDACTED_SECRET]`.
* **Raw Thought Redaction:** Unfiltered internal chain-of-thought scratchpads (`thought`, `scratchpad`, `raw_cot`) are replaced with `[REDACTED_THOUGHT]`.

---

## 4. Lifecycle Timers and Performance Metrics

The `MetricsCollector` tracks operational incident lifecycle timers and system latency histograms:

### Lifecycle Timers
* `time_to_detection`: Time from event arrival to incident creation.
* `time_to_investigation_start`: Time until LangGraph workflow begins.
* `time_to_diagnosis`: Duration to formulate confirmed hypothesis.
* `time_to_approval`: Pending approval dwell time.
* `time_to_execution`: Provider action execution duration.
* `time_to_recovery`: Time until post-action verification succeeds.
* `time_to_resolution`: Total end-to-end incident lifecycle duration.

### Latency Histograms
* `agent_latency`, `tool_latency`, `retrieval_latency`, `mcp_latency`, `policy_latency`.

### Reliability Counters
* `error_rate`, `retry_rate`, `action_denial_rate`.

---

## 5. Exporter Compatibility

The `OpenTelemetryJsonExporter` serializes collected spans and metric snapshots to standard JSON formats compatible with OTLP collectors, CloudWatch, Datadog, or Grafana Tempo/Mimir.
