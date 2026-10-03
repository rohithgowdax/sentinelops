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

## Agent Investigation Generalization (Slice 2)

In Slice 2, SentinelOps extended provider neutrality to the AI investigation layer. The LangGraph agent consumes canonical `Incident` objects and queries operational telemetry solely through the `TelemetryEvidenceProvider` capability protocol:

```python
class TelemetryEvidenceProvider(Protocol):
    async def query_recent_telemetry(self, resource: str, metric: str, window_seconds: int = 300) -> dict[str, Any]: ...
    async def compare_telemetry_baseline(self, resource: str, metric: str, current_window: int = 300, baseline_window: int = 3600) -> dict[str, Any]: ...
    async def get_incident_trigger_context(self, incident: Incident) -> dict[str, Any]: ...
```

The LangGraph investigation loop contains zero branches on incident sources or telemetry origins, proven via automated AST parsing.

## Knowledge Capability Generalization (Slice 3)

In Slice 3, organizational knowledge retrieval was introduced without coupling the core agent to any vector database vendor. The agent communicates with knowledge repositories exclusively through the `KnowledgeProvider` capability protocol:

```python
class KnowledgeProvider(Protocol):
    async def search(self, query: KnowledgeQuery) -> list[KnowledgeResult]: ...
    async def index_chunks(self, chunks: list[KnowledgeChunk]) -> int: ...
```

### Knowledge Generalization Invariants
1. **Zero Vector DB Imports in Agent:** Agent nodes, prompts, state, and graph never import `qdrant_client`, `chromadb`, `pymilvus`, `pinecone`, or LLM vendor SDKs.
2. **Provider Interchangeability:** Both `InMemoryKnowledgeProvider` (zero-dependency for CI/offline testing) and `QdrantKnowledgeProvider` (production vector store) implement the identical protocol and produce identical canonical `KnowledgeResult` structures.
3. **Canonical Evidence Grounding:** Telemetry evidence (`kind="metric"`) and knowledge evidence (`kind="runbook"`, `"postmortem"`, etc.) are both normalized into `InvestigationEvidence` records with explicit citation provenance (`document_id`, `chunk_id`, `source`, `retrieval_score`, `rank`, `content_snippet`).
4. **Graceful Fallback:** If the vector database or knowledge service fails, the agent continues investigation using live operational telemetry without failing.

## Architectural Invariants

1. **No provider branching in the core.** The only permitted location for provider-specific logic is in an adapter or integration provider.
2. **Adapters and Providers are stateless.** Normalization and retrieval operations do not leak mutable cross-request state.
3. **Canonical models are the API surface.** EventBus, OperationalStore, Detection Engine, LangGraph, and Knowledge Subsystem communicate strictly in canonical types.
4. **Raw payload and provenance are preserved.** Raw payloads and chunk snippets are preserved for auditing without leaking vendor coupling into business logic.
5. **New providers require zero core modification.** Adding a new telemetry source requires only a `TelemetryAdapter`; adding a new vector store requires only a `KnowledgeProvider`.

