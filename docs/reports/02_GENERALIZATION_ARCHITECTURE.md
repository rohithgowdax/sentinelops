# SentinelOps — Generalization Architecture

## Purpose

This document describes the architectural mechanism by which SentinelOps achieves provider neutrality: the ability to accept telemetry from any external system, normalize it into a single canonical representation, and process it through a single shared pipeline.

## The Problem

Observability ecosystems are fragmented. A company might emit metrics from OpenTelemetry, custom agents, Datadog DogStatsD, Prometheus, and CloudWatch simultaneously. Building a detection and remediation engine that hard-codes awareness of each format creates:

- Brittle branching: `if provider == "datadog"` scattered through business logic
- Duplicated detection rules per format
- Format-coupled incidents: changing a field name in one integration breaks detection
- Untestable core: can't test the detection engine independently of infrastructure

## The Solution: Canonical Model + Adapter Pattern

```
External Format A (OTel)        External Format B (Custom JSON)
        │                                  │
   Adapter A                          Adapter B
        │                                  │
        └──────────┬───────────────────────┘
                   │
         Canonical TelemetryRecord
                   │
          ┌────────┼────────────┐
          │        │            │
        EventBus  Worker      Store
          │        │            │
          └────────┴────────────┘
                   │
          Detection Engine
          (no provider knowledge)
                   │
          Canonical Incident
                   │
          incident.created → EventBus
```

## Canonical Domain Layer

The `sentinelops.domain` package contains no imports from any external observability vendor. It defines:

| Model | Purpose |
|---|---|
| `TelemetryRecord` | Normalised telemetry envelope |
| `MetricObservation` | A single metric data point |
| `LogRecord` | A normalised log entry |
| `ResourceIdentity` | Provider-neutral service/resource identity |
| `TelemetrySource` | Records which adapter produced this record |
| `Incident` | Canonical incident created by the Detection Engine |
| `EvidenceItem` | Evidence attached to an incident |

## Adapter Contract

Every adapter implements `TelemetryAdapter`:

```python
class TelemetryAdapter(Protocol):
    @property
    def provider(self) -> str: ...
    @property
    def integration_id(self) -> str: ...
    def normalize(self, raw: dict[str, Any]) -> TelemetryRecord: ...
```

The adapter is the **only place** where external field names appear. The core never sees `err_pct`, `svc`, `timeUnixNano`, or any other vendor-specific identifier.

## The Two-Provider Proof (Slice 1)

### Adapter A: OTel-like JSON

External fields:
- `resourceMetrics[].resource.attributes[]` → `ResourceIdentity`
- `service.name` → `resource.service_name`
- `deployment.environment` → `resource.environment`
- `metrics[].name` → `metric.name`
- `dataPoints[].asDouble` → `metric.value`
- `timeUnixNano` → `timestamp`

### Adapter B: Custom JSON

External fields:
- `svc` → `resource.service_name`
- `env` → `resource.environment`
- `metric_name` (+ name-mapping table) → `metric.name`
- `metric_value` (+ unit scaling: percent → ratio) → `metric.value`
- `time` → `timestamp`
- `tags` → `metric.dimensions`

### Normalisation Invariant

After normalization:
- `record_a.resource.service_name == record_b.resource.service_name`
- `record_a.metric.name == record_b.metric.name == "http.error_rate"`
- `record_a.metric.value ≈ record_b.metric.value` (to floating-point precision)
- `record_a.signal_type == record_b.signal_type == SignalType.METRIC`

This invariant is **enforced by the generalization contract tests** in `tests/contract/test_generalization.py`.

## Detection Engine Provider Neutrality

The `evaluate_rule()` function operates exclusively on `TelemetryRecord` fields:
- `record.metric.name` (canonical)
- `record.metric.value` (canonical)
- `record.resource.service_name` (canonical)

It never accesses `record.source.provider`. If it did, the contract test `test_detector_does_not_inspect_provider` would fail because both adapters produce different provider values but must produce the same detection outcome.

## Architectural Invariants

1. **No provider branching in the core.** The only permitted location for provider-specific logic is in an adapter's `normalize()` method.
2. **Adapters are stateless.** Each `normalize()` call is independent with no shared mutable state.
3. **Canonical models are the API surface.** The EventBus, OperationalStore, and Detection Engine only accept and return canonical types.
4. **Raw payload is preserved.** The `raw_payload` field retains the original external data for debugging without affecting business logic.
5. **New providers require only a new adapter.** No changes to detection, storage, or API code are required.

## Limitations in Slice 1

- Adapters are registered manually (injected at startup). Future slices will add a plugin/discovery mechanism.
- Metric name mapping table in Adapter B is hardcoded. Future slices may load from configuration.
- Only metric signals are handled. Log and trace adapters are designed but not yet implemented.
