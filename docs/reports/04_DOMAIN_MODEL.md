# SentinelOps — Domain Model

## Purpose

The domain model is the provider-neutral internal language of SentinelOps. Every external system is normalized into these types before entering any core pipeline component. No adapter, store, or detection rule may bypass this normalization.

## Design Principles

1. **No vendor field names.** The domain model contains no OTel, Datadog, Prometheus, or CloudWatch identifiers.
2. **Information preservation.** The `raw_payload` field retains the original external data without driving any business logic.
3. **Explicit signal types.** A `TelemetryRecord` carries exactly one signal payload (metric or log), disambiguated by `signal_type`.
4. **Typed enums.** All categorical values use Python Enum types, not strings, to prevent typos and enable IDE completion.
5. **Idempotency handles.** Every domain object has a stable ID field for deduplication.

---

## Telemetry Models

### `SignalType`
```python
class SignalType(str, Enum):
    METRIC = "metric"
    LOG = "log"
    TRACE = "trace"
    EVENT = "event"
```

### `TelemetrySource`
Identifies which adapter produced a telemetry record.

| Field | Type | Description |
|---|---|---|
| `provider` | `str` | Logical provider name: `"otel"`, `"custom_json"`, `"datadog"` |
| `integration_id` | `str` | Specific adapter instance ID |
| `raw_format_version` | `str\|None` | External format version if available |

> **Invariant:** The core pipeline NEVER branches on `provider`. This field is for traceability only.

### `ResourceIdentity`
Provider-neutral service/resource identity.

| Field | Type | Description |
|---|---|---|
| `service_name` | `str` | Canonical service name |
| `service_namespace` | `str\|None` | Service group/team namespace |
| `service_version` | `str\|None` | Deployed version |
| `environment` | `str\|None` | `"production"`, `"staging"`, etc. |
| `host_name` | `str\|None` | Host or node name |
| `attributes` | `dict[str, str]` | Additional free-form attributes |

### `MetricObservation`
A single canonical metric data point.

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Canonical metric name: `"http.error_rate"`, `"http.latency.p99"` |
| `value` | `float` | Numeric value in canonical unit |
| `unit` | `str\|None` | Unit of measure: `"ratio"`, `"ms"`, `"requests"` |
| `dimensions` | `dict[str, str]` | Metric labels/dimensions |

> **Unit invariant:** Adapters must normalize units to canonical form. `CustomJsonAdapter` converts percent (0–100) to ratio (0–1) because the canonical unit for `http.error_rate` is ratio, matching OTel convention.

### `TelemetryRecord`
The top-level telemetry envelope. Every inbound signal becomes exactly one `TelemetryRecord`.

| Field | Type | Description |
|---|---|---|
| `event_id` | `str` | Globally unique UUID (idempotency key) |
| `timestamp` | `datetime` | Event timestamp in UTC |
| `signal_type` | `SignalType` | `metric`, `log`, `trace`, `event` |
| `source` | `TelemetrySource` | Which adapter produced this |
| `resource` | `ResourceIdentity` | Which service/resource emitted it |
| `metric` | `MetricObservation\|None` | Set when `signal_type == METRIC` |
| `log` | `LogRecord\|None` | Set when `signal_type == LOG` |
| `trace_id` | `str\|None` | Distributed trace ID if available |
| `span_id` | `str\|None` | Span ID if available |
| `attributes` | `dict[str, Any]` | Additional free-form context |
| `raw_payload` | `dict\|None` | Original untransformed external payload |

**JSON Example:**
```json
{
  "event_id": "3f7a1c2e-...",
  "timestamp": "2026-10-01T14:37:12+00:00",
  "signal_type": "metric",
  "source": {
    "provider": "otel",
    "integration_id": "otel-json-v1"
  },
  "resource": {
    "service_name": "payments-service",
    "environment": "production",
    "service_namespace": "commerce"
  },
  "metric": {
    "name": "http.error_rate",
    "value": 0.18,
    "unit": "ratio",
    "dimensions": {}
  },
  "raw_payload": { "...original OTel payload..." }
}
```

---

## Incident Models

### `IncidentSeverity`
```
LOW | MEDIUM | HIGH | CRITICAL
```

### `IncidentStatus`
```
OPEN | INVESTIGATING | RESOLVED | CLOSED
```

### `TriggerType`
```
METRIC_THRESHOLD | LOG_PATTERN | ANOMALY | EXTERNAL
```

### `EvidenceItem`
A piece of evidence attached to an incident at creation time.

| Field | Type | Description |
|---|---|---|
| `evidence_id` | `str` | Auto-generated UUID |
| `kind` | `str` | `"metric"`, `"log"`, `"event"` |
| `description` | `str` | Human-readable description |
| `value` | `Any\|None` | The observed value |
| `telemetry_event_id` | `str\|None` | Link back to the triggering TelemetryRecord |
| `timestamp` | `datetime\|None` | When this evidence was captured |
| `attributes` | `dict` | Rule context, thresholds, etc. |

### `Incident`
The canonical incident. Created deterministically by the Detection Engine.

| Field | Type | Description |
|---|---|---|
| `incident_id` | `str` | `"INC-XXXXXXXX"` (auto-generated) |
| `created_at` | `datetime` | UTC timestamp |
| `updated_at` | `datetime` | UTC timestamp |
| `severity` | `IncidentSeverity` | |
| `status` | `IncidentStatus` | Starts as `OPEN` |
| `service_name` | `str` | Canonical service name |
| `service_namespace` | `str\|None` | |
| `environment` | `str\|None` | |
| `trigger_type` | `TriggerType` | How this incident was created |
| `trigger_rule_id` | `str\|None` | Which rule fired |
| `trigger_rule_name` | `str\|None` | Human-readable rule name |
| `initial_evidence` | `list[EvidenceItem]` | Evidence at detection time |
| `title` | `str` | Deterministically generated title |
| `description` | `str` | Deterministically generated description |
| `source_provider` | `str` | Which provider context triggered detection |
| `source_integration_id` | `str` | Which integration/rule triggered detection |
| `episode_key` | `str` | Stable deduplication key: `rule_id::service::env` |
| `context` | `dict` | Free-form context (observed value, threshold, etc.) |

> **LLM invariant:** No LLM generates or modifies an Incident in slice 1. All fields are populated deterministically from rule evaluation.

**JSON Example:**
```json
{
  "incident_id": "INC-A1B2C3D4",
  "created_at": "2026-10-01T14:37:22+00:00",
  "updated_at": "2026-10-01T14:37:22+00:00",
  "severity": "critical",
  "status": "open",
  "service_name": "payments-service",
  "environment": "production",
  "trigger_type": "metric_threshold",
  "trigger_rule_id": "rule-001-elevated-service-errors",
  "title": "[CRITICAL] Elevated Service Error Rate on payments-service",
  "episode_key": "rule-001-elevated-service-errors::payments-service::production",
  "initial_evidence": [
    {
      "kind": "metric",
      "description": "Rule 'Elevated Service Error Rate' fired: http.error_rate gt 0.1 (observed=0.18)",
      "value": 0.18
    }
  ]
}
```

---

## Domain Events

### `TelemetryReceivedEvent`
Published to `sentinel:telemetry` when canonical telemetry is produced.

```json
{
  "event_id": "uuid",
  "event_type": "telemetry.received",
  "occurred_at": "2026-10-01T14:37:12+00:00",
  "schema_version": "1.0",
  "telemetry": { "...TelemetryRecord..." }
}
```

### `IncidentCreatedEvent`
Published to `sentinel:incidents` when an incident is created.

```json
{
  "event_id": "uuid",
  "event_type": "incident.created",
  "occurred_at": "2026-10-01T14:37:22+00:00",
  "schema_version": "1.0",
  "incident": { "...Incident..." }
}
```

---

## Investigation Domain Models (Slice 2)

### `InvestigationStatus`
```python
class InvestigationStatus(str, Enum):
    INVESTIGATING = "investigating"
    DIAGNOSED = "diagnosed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INVESTIGATION_FAILED = "investigation_failed"
```

### `InvestigationStep` & `InvestigationPlan`
Structured plan formulated by the planning node.

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique step identifier (e.g. `'query_telemetry'`, `'baseline_comparison'`) |
| `description` | `str` | Actionable explanation of step intent |
| `capability` | `str` | Required generic capability (`'telemetry'`, `'baseline'`, `'trigger_context'`) |
| `params` | `dict[str, Any]` | Target metric, lookback, and evaluation params |

### `InvestigationEvidence`
Canonical structured evidence gathered through capability providers.

| Field | Type | Description |
|---|---|---|
| `evidence_id` | `str` | Stable ID referenced by hypotheses and diagnoses (e.g. `'E01'`) |
| `incident_id` | `str` | Associated incident ID |
| `source_type` | `str` | Source capability (`'telemetry'`, `'baseline_comparison'`, `'trigger_context'`) |
| `source_ref` | `str` | Metric name or rule identifier |
| `resource` | `str` | Target service or resource identity |
| `signal` | `str` | Metric or signal name |
| `observation` | `dict[str, Any]` | Quantitative observations (min, max, avg, ratio, samples) |
| `relevance` | `str` | Diagnostic relevance of this finding |

### `Hypothesis`
Candidate root cause formulated by correlating evidence.

| Field | Type | Description |
|---|---|---|
| `hypothesis_id` | `str` | Identifier (e.g. `'H01'`) |
| `hypothesis` | `str` | Plausible root cause explanation |
| `confidence` | `float` | Evaluated confidence (0.0 to 1.0) |
| `supporting_evidence_ids` | `list[str]` | Mandatory references to collected evidence IDs |
| `contradicting_evidence_ids` | `list[str]` | Any contradictory evidence items |

### `Diagnosis`
Evidence-backed root cause synthesis.

| Field | Type | Description |
|---|---|---|
| `root_cause` | `str` | Concise root cause summary |
| `confidence` | `float` | Diagnostic certainty (0.0 to 1.0) |
| `supporting_evidence` | `list[str]` | Mandatory list of valid evidence IDs |
| `explanation` | `str` | Grounded reasoning connecting evidence to root cause |
| `recommended_actions` | `list[str]` | Non-executable advisory actions |

### `VerificationResult`
Outcome of the verification gate node.

| Field | Type | Description |
|---|---|---|
| `is_verified` | `bool` | True if evidence threshold and consistency checks pass |
| `confidence` | `float` | Verification confidence rating |
| `reason` | `str` | Explanation of verification verdict |
| `missing_evidence` | `list[str]` | Gaps identified if unverified |

### `InvestigationResult`
Terminal immutable record of the completed investigation.

| Field | Type | Description |
|---|---|---|
| `incident_id` | `str` | Associated incident ID |
| `status` | `InvestigationStatus` | `DIAGNOSED`, `INSUFFICIENT_EVIDENCE`, `INVESTIGATION_FAILED` |
| `diagnosis` | `Diagnosis\|None` | Structured diagnosis if achieved |
| `confidence` | `float` | Overall confidence score |
| `supporting_evidence` | `list[InvestigationEvidence]` | Complete structured evidence gathered |
| `investigation_steps` | `list[InvestigationStep]` | Planned steps executed |
| `tool_calls_summary` | `list[dict]` | Audit log of capability queries executed |
| `duration_seconds` | `float` | Total execution wall clock time |
| `iteration_count` | `int` | Number of loops completed (bounded by max 3) |
| `completed_at` | `datetime` | UTC completion timestamp |

---

## What is Excluded

The domain model intentionally excludes:
- Vendor-specific field names (`err_pct`, `svc`, `timeUnixNano`, etc.)
- HTTP/transport-layer fields
- Remediation execution or mutation commands (Slice 2 is strictly read-only investigation)
- Vector embeddings or RAG indices (deferred to future slices)

