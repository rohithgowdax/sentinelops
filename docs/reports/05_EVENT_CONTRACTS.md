# SentinelOps — Event Contracts

## Purpose

This document specifies the event contracts for the two Redis Streams used in slice 1: `sentinel:telemetry` and `sentinel:incidents`. These contracts define the schema, delivery semantics, and consumer responsibilities for all producers and consumers.

## Streams Overview

| Stream | Purpose | Publisher | Consumer |
|---|---|---|---|
| `sentinel:telemetry` | Canonical telemetry events | Adapters (via simulator/ingest API) | Telemetry Worker |
| `sentinel:incidents` | Incident lifecycle events | Detection Loop | Future orchestrator |

## Delivery Semantics

- **At-least-once delivery** via Redis Streams consumer groups (`XREADGROUP`).
- Messages are **not auto-acknowledged**. The consumer must call `XACK` after successful processing.
- Failed messages remain in the **Pending-Entries List (PEL)** and can be reclaimed by other consumers in the group.
- Messages are **never silently dropped**. A parse failure logs an error but does not ACK the message.

## Consumer Groups

Both streams use a single consumer group `sentinelops-workers` in slice 1.

```
Stream: sentinel:telemetry
Consumer Group: sentinelops-workers
  Consumer: worker-1
  Consumer: worker-2  (if scaled)
```

Consumer groups are created automatically at worker startup with `MKSTREAM=True`. The group starts reading from position `0` (beginning of stream). In production, you would start new groups at `$` (latest) for fresh deployments.

## Idempotency

Every event has a stable `event_id` (UUID) carried in the payload. The OperationalStore uses `ON CONFLICT DO NOTHING` on this ID, so replayed messages are safely ignored.

---

## `sentinel:telemetry` Event Schema

### Redis Stream Entry

```
Stream Key:  sentinel:telemetry
Entry Fields:
  event_id: <uuid>           # top-level for fast inspection without payload parse
  payload:  <JSON string>    # full TelemetryReceivedEvent JSON
```

### `TelemetryReceivedEvent` Schema

```json
{
  "event_id": "3f7a1c2e-4b5d-6e7f-8a9b-0c1d2e3f4a5b",
  "event_type": "telemetry.received",
  "occurred_at": "2026-10-01T14:37:12.000000+00:00",
  "schema_version": "1.0",
  "telemetry": {
    "event_id": "7a8b9c0d-...",
    "timestamp": "2026-10-01T14:37:12+00:00",
    "signal_type": "metric",
    "source": {
      "provider": "otel",
      "integration_id": "otel-json-v1",
      "raw_format_version": null
    },
    "resource": {
      "service_name": "payments-service",
      "service_namespace": "commerce",
      "service_version": null,
      "environment": "production",
      "host_name": null,
      "attributes": {}
    },
    "metric": {
      "name": "http.error_rate",
      "value": 0.18,
      "unit": "ratio",
      "dimensions": {}
    },
    "log": null,
    "trace_id": null,
    "span_id": null,
    "attributes": {},
    "raw_payload": { "...original external payload..." }
  }
}
```

### Consumer Responsibilities

1. Parse the `payload` field into `TelemetryReceivedEvent`.
2. Call `store.save_telemetry(event.telemetry)`.
3. On success: call `XACK sentinel:telemetry <group> <entry_id>`.
4. On failure: log error, do NOT ack (message stays in PEL).

---

## `sentinel:incidents` Event Schema

### Redis Stream Entry

```
Stream Key:  sentinel:incidents
Entry Fields:
  event_id: <uuid>
  payload:  <JSON string>
```

### `IncidentCreatedEvent` Schema

```json
{
  "event_id": "b1c2d3e4-...",
  "event_type": "incident.created",
  "occurred_at": "2026-10-01T14:37:22.000000+00:00",
  "schema_version": "1.0",
  "incident": {
    "incident_id": "INC-A1B2C3D4",
    "created_at": "2026-10-01T14:37:22+00:00",
    "updated_at": "2026-10-01T14:37:22+00:00",
    "severity": "critical",
    "status": "open",
    "service_name": "payments-service",
    "service_namespace": null,
    "environment": "production",
    "trigger_type": "metric_threshold",
    "trigger_rule_id": "rule-001-elevated-service-errors",
    "trigger_rule_name": "Elevated Service Error Rate",
    "initial_evidence": [
      {
        "evidence_id": "...",
        "kind": "metric",
        "description": "Rule 'Elevated Service Error Rate' fired: http.error_rate gt 0.1 (observed=0.18, samples=5)",
        "value": 0.18,
        "telemetry_event_id": null,
        "timestamp": "2026-10-01T14:37:22+00:00",
        "attributes": {
          "rule_id": "rule-001-elevated-service-errors",
          "operator": "gt",
          "threshold": "0.1",
          "aggregation": "latest",
          "window_seconds": "60",
          "sample_count": "5"
        }
      }
    ],
    "title": "[CRITICAL] Elevated Service Error Rate on payments-service",
    "description": "Detection rule 'Elevated Service Error Rate' (ID: rule-001-elevated-service-errors) fired for service 'payments-service'...",
    "source_provider": "sentinelops-detector",
    "source_integration_id": "rule-001-elevated-service-errors",
    "episode_key": "rule-001-elevated-service-errors::payments-service::production",
    "context": {
      "observed_value": 0.18,
      "threshold": 0.1,
      "window_seconds": 60,
      "sample_count": 5
    }
  }
}
```

### Consumer Responsibilities (Slice 2+)

In slice 1, the incident stream has no active consumer. Future slices will attach:
- The LangGraph orchestrator for investigation
- Notification dispatchers
- SLA tracking

---

## Schema Versioning

All events carry `schema_version: "1.0"`. Future breaking changes must increment this version. Consumers should check this field before parsing the payload.

Breaking changes require:
1. Increment `schema_version`
2. Update producer to write new schema
3. Update all consumers to handle both old and new schema during migration window
4. Deprecate old schema version

## Failure Handling

| Failure Scenario | Outcome |
|---|---|
| Parse error in consumer | Error logged; message stays in PEL; not lost |
| Store write failure | Error logged; message stays in PEL; retry on next poll |
| Consumer process crash | Messages remain in PEL; recovered when consumer restarts |
| Duplicate event_id | ON CONFLICT DO NOTHING in store; safe to replay |
| Redis restart | Stream data persists (unless `--save` is disabled in Redis config) |

## Limitations in Slice 1

- No DLQ (dead-letter queue) for permanently failed messages — future slice
- PEL recovery (XPENDING + XCLAIM) not implemented — future slice
- No stream trimming / retention policy configured — future slice
- `sentinel:incidents` has no active consumer in slice 1
