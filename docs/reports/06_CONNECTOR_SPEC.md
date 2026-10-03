# SentinelOps — Connector / Adapter Specification

## Purpose

This document specifies how external telemetry sources are integrated into SentinelOps via adapters, what contract each adapter must satisfy, and how to add new adapters.

## The TelemetryAdapter Protocol

```python
class TelemetryAdapter(Protocol):
    @property
    def provider(self) -> str: ...
    
    @property
    def integration_id(self) -> str: ...
    
    def normalize(self, raw: dict[str, Any]) -> TelemetryRecord: ...
```

**Rules:**
- `normalize()` must be **synchronous and stateless**. No I/O, no caching.
- `normalize()` must raise `ValueError` for structurally invalid payloads.
- `normalize()` must preserve the original payload in `raw_payload`.
- `normalize()` must NOT silently default unparseable values — fail explicitly.
- The adapter is the **only place** where external field names appear.
- No adapter may import from `sentinelops.detection`, `sentinelops.storage`, or `sentinelops.api`.

---

## Adapter A: OtelLikeAdapter

**Module:** `sentinelops.integrations.telemetry.otel_like.adapter`  
**Provider:** `"otel"`  
**Integration ID:** `"otel-json-v1"`

### Supported Formats

**Format 1: Full OTel resourceMetrics envelope**
```json
{
  "resourceMetrics": [{
    "resource": {
      "attributes": [
        {"key": "service.name", "value": {"stringValue": "payments-service"}},
        {"key": "deployment.environment", "value": {"stringValue": "production"}}
      ]
    },
    "scopeMetrics": [{
      "metrics": [{
        "name": "http.error_rate",
        "unit": "ratio",
        "gauge": {
          "dataPoints": [{
            "timeUnixNano": "1727789832000000000",
            "asDouble": 0.18
          }]
        }
      }]
    }]
  }]
}
```

**Format 2: Simplified shorthand (used by simulator/tests)**
```json
{
  "resource": {
    "service.name": "payments-service",
    "deployment.environment": "production"
  },
  "metric": {"name": "http.error_rate", "value": 0.18, "unit": "ratio"},
  "timestamp": "2026-10-01T14:37:12Z"
}
```

### Field Mapping

| External Field (OTel) | Canonical Field |
|---|---|
| `resource.attributes[service.name]` | `resource.service_name` |
| `resource.attributes[service.namespace]` | `resource.service_namespace` |
| `resource.attributes[deployment.environment]` | `resource.environment` |
| `resource.attributes[service.version]` | `resource.service_version` |
| `metrics[].name` | `metric.name` |
| `metrics[].unit` | `metric.unit` |
| `dataPoints[].asDouble` or `asInt` | `metric.value` |
| `dataPoints[].timeUnixNano` | `timestamp` (converted from nanoseconds) |
| `dataPoints[].attributes` | `metric.dimensions` |
| entire raw object | `raw_payload` |

### Error Cases

| Condition | Behaviour |
|---|---|
| Unrecognized top-level structure | `ValueError: unrecognised payload shape` |
| Empty `resourceMetrics` list | `ValueError: resourceMetrics is empty` |
| Empty `scopeMetrics` | `ValueError: scopeMetrics is empty` |
| No dataPoints | `ValueError: no dataPoints for metric` |

---

## Adapter B: CustomJsonAdapter

**Module:** `sentinelops.integrations.telemetry.custom_json.adapter`  
**Provider:** `"custom_json"`  
**Integration ID:** `"custom-json-v1"` (overridable per-event via `src_id`)

### Format

```json
{
  "svc": "payments-service",
  "env": "production",
  "ns": "commerce",
  "metric_name": "err_pct",
  "metric_value": 18.4,
  "unit": "percent",
  "time": "2026-10-01T14:37:12Z",
  "tags": {"region": "us-east-1"},
  "src_id": "custom-agent-001"
}
```

### Field Mapping

| External Field | Canonical Field | Notes |
|---|---|---|
| `svc` | `resource.service_name` | Required |
| `env` or `environment` | `resource.environment` | Optional |
| `ns` or `namespace` | `resource.service_namespace` | Optional |
| `ver` or `version` | `resource.service_version` | Optional |
| `host` | `resource.host_name` | Optional |
| `metric_name` | `metric.name` | Required; see name mapping below |
| `metric_value` | `metric.value` | Required; see unit scaling below |
| `unit` | `metric.unit` | Optional; affects scaling |
| `time` or `timestamp` | `timestamp` | Optional; defaults to now() |
| `tags` | `metric.dimensions` | Optional |
| `src_id` | `source.integration_id` | Optional override |
| entire raw object | `raw_payload` | Always preserved |

### Metric Name Mapping

| Custom Name | Canonical Name |
|---|---|
| `err_pct` | `http.error_rate` |
| `error_rate` | `http.error_rate` |
| `lat_p99_ms` | `http.latency.p99` |
| `latency_p99` | `http.latency.p99` |
| `req_per_sec` | `http.request_rate` |
| `err_total` | `http.error_total` |
| Any other | Passed through unchanged |

This mapping is located **only in the adapter**, never in the core.

### Unit Scaling

If `unit` is `"percent"` or `"%"` and `metric_value > 1.0`, the value is divided by 100 and the unit is changed to `"ratio"`. This ensures canonical semantic equivalence with OTel-style adapters that use the ratio convention.

Example: `metric_value: 18.4, unit: "percent"` → `metric.value: 0.184, metric.unit: "ratio"`

### Required Fields

`svc`, `metric_name`, `metric_value` are required. Missing any raises `ValueError: missing required fields`.

### Error Cases

| Condition | Behaviour |
|---|---|
| Missing required fields | `ValueError: missing required fields: [...]` |
| Non-numeric `metric_value` | `ValueError: metric_value must be numeric` |
| Unparseable timestamp | `ValueError: cannot parse timestamp` |

---

## How to Add a New Adapter

1. Create a new module under `src/sentinelops/integrations/telemetry/<provider_name>/adapter.py`
2. Define a class implementing the `TelemetryAdapter` protocol:
   ```python
   class MyNewAdapter:
       @property
       def provider(self) -> str:
           return "my_provider"
       
       @property
       def integration_id(self) -> str:
           return "my-adapter-v1"
       
       def normalize(self, raw: dict[str, Any]) -> TelemetryRecord:
           # Map external fields → canonical types
           # Raise ValueError for invalid inputs
           # Always set raw_payload=raw
           ...
   ```
3. Add the adapter to the integration layer `__init__.py`
4. Register it in the ingestion producer (future: via plugin registry)
5. Add unit tests in `tests/unit/test_adapter_<provider>.py`
6. Add a generalization contract test entry in `tests/contract/test_generalization.py`

**Never:**
- Import from `sentinelops.detection`, `sentinelops.storage`, or `sentinelops.api`
- Store mutable state in the adapter
- Call external services from `normalize()`
- Default silently to arbitrary values for required fields

---

## Capability Provider: TelemetryEvidenceProvider (Slice 2)

**Module:** `sentinelops.domain.contracts.protocols` / `sentinelops.capabilities.evidence.telemetry_evidence`

The agent layer must never touch physical databases, Redis, or raw SQL. Instead, it interacts with the `TelemetryEvidenceProvider` protocol:

```python
class TelemetryEvidenceProvider(Protocol):
    async def query_recent_telemetry(
        self,
        service_name: str,
        metric_name: str,
        lookback_seconds: int = 300,
    ) -> dict[str, Any]: ...

    async def compare_telemetry_baseline(
        self,
        service_name: str,
        metric_name: str,
        current_window_seconds: int = 120,
        baseline_window_seconds: int = 600,
    ) -> dict[str, Any]: ...

    async def get_incident_trigger_context(
        self,
        incident: Incident,
    ) -> dict[str, Any]: ...
```

### Decoupling Rules:
- Agent nodes query this capability abstraction and translate outputs into `InvestigationEvidence` objects.
- Concrete implementation `PostgresTelemetryEvidenceProvider` wraps `OperationalStore` without exposing database engine details to LangGraph.
- Zero provider-specific branching inside capability methods.

