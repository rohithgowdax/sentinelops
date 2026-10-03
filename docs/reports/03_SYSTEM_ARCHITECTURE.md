# SentinelOps — System Architecture (Slice 1)

## Purpose

This document describes the implemented system architecture for the first SentinelOps vertical slice: the telemetry ingestion → detection → incident publication pipeline.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│  External World                                                          │
│                                                                          │
│  ┌────────────────┐        ┌────────────────────┐                       │
│  │  OTel-like     │        │  Custom JSON Agent │                       │
│  │  JSON Source   │        │  (Adapter B)       │                       │
│  └───────┬────────┘        └────────┬───────────┘                       │
└──────────┼─────────────────────────┼─────────────────────────────────── ┘
           │ Adapter A               │ Adapter B
           │ normalize()             │ normalize()
           └──────────┬──────────────┘
                      │
               TelemetryRecord
               (canonical)
                      │
                      ▼
           ┌──────────────────────┐
           │  Redis Streams       │
           │  sentinel:telemetry  │
           └──────────┬───────────┘
                      │ XREADGROUP (consumer group)
                      ▼
           ┌──────────────────────┐
           │  Telemetry Worker    │
           │  (ingestion layer)   │
           └──────────┬───────────┘
                      │ save_telemetry()
                      ▼
           ┌──────────────────────┐
           │  PostgreSQL          │
           │  OperationalStore    │
           │  (telemetry table)   │
           └──────────┬───────────┘
                      │ query_recent_metrics()
                      ▼
           ┌──────────────────────┐
           │  Detection Loop      │
           │  (periodic, 10s)     │
           │  evaluate_rule()     │
           └──────────┬───────────┘
                      │ fires → save_incident()
                      │        publish_incident()
                      ▼
           ┌────────────────────────────┐
           │  PostgreSQL                │
           │  (incidents table)         │
           └────────────────────────────┘
                      +
           ┌────────────────────────────┐
           │  Redis Streams             │
           │  sentinel:incidents        │
           └──────────┬─────────────────┘
                      │
        ┌─────────────┴─────────────────┐
        │                               │ XREADGROUP
        ▼                               ▼
┌──────────────────────┐   ┌───────────────────────────────┐
│  FastAPI             │   │  SentinelOps Orchestrator     │
│  GET /health         │   │  (orchestrator/service.py)    │
│  GET /incidents      │   └─────────────┬─────────────────┘
│  GET /incidents/{id} │                 │ incident.created
│  GET /incidents/     │                 ▼
│      {id}/           │   ┌───────────────────────────────┐
│      investigation   │   │  LangGraph Investigation Loop │
└──────────────────────┘   │  (agent/graph.py)             │
                           │                               │
                           │  START                        │
                           │    │                          │
                           │    ▼                          │
                           │  incident_intake              │
                           │    │                          │
                           │    ▼                          │
                           │  build_investigation_plan     │
                           │    │                          │
                           │    ▼                          │
                           │  collect_evidence ◄────────┐  │
                           │    │ (via Provider)        │  │
                           │    ▼                       │  │
                           │  analyze_evidence          │  │
                           │    │                       │  │
                           │    ▼                       │  │
                           │  diagnose                  │  │
                           │    │                       │  │
                           │    ▼                       │  │
                           │  verify_diagnosis          │  │
                           │    │ (is_verified?)        │  │
                           │    ├─ insufficient & iter<3┘  │
                           │    ▼                          │
                           │  finalize                     │
                           │    │                          │
                           │    ▼                          │
                           │  END                          │
                           └─────────────┬─────────────────┘
                                         │ save_investigation()
                                         ▼
                           ┌───────────────────────────────┐
                           │  PostgreSQL                   │
                           │  (investigations table)       │
                           └───────────────────────────────┘
```

## Component Responsibilities

### Adapters (`integrations/telemetry/`)

- **Only** location where external field names appear
- Stateless `normalize(raw: dict) → TelemetryRecord`
- Raises `ValueError` on invalid payloads
- Preserves `raw_payload` for debugging

### EventBus (`integrations/event_bus/redis_bus.py`)

- Redis Streams with consumer groups
- At-least-once delivery
- Explicit ACK pattern — failed messages remain in PEL
- Streams: `sentinel:telemetry`, `sentinel:incidents`

### Telemetry Worker (`ingestion/worker.py`)

- Consumes from `sentinel:telemetry` consumer group
- Calls `store.save_telemetry()` (idempotent on `event_id`)
- ACKs only after successful persistence
- Does not branch on `source.provider`

### OperationalStore (`storage/postgres_store.py`)

- PostgreSQL with SQLAlchemy async
- Idempotent upserts via `ON CONFLICT DO NOTHING`
- `query_recent_metrics()`: time-window query on canonical fields
- `get_active_episode()`: deduplication check

### Detection Engine (`detection/`)

- `rules.py`: YAML rule schema + loader
- `engine.py`: pure `evaluate_rule()` function (no I/O)
- `loop.py`: periodic orchestration + incident creation

### API (`api/main.py`)

- Minimal FastAPI: `/health`, `/incidents`, `/incidents/{id}`, `/incidents/{id}/investigation`
- No business logic in routes
- Reads from OperationalStore only

### Orchestrator Service (`orchestrator/service.py`)

- Consumes `IncidentCreatedEvent` from `sentinel:incidents` stream via consumer group
- Manages durable state checkpointing using `incident_id` as the thread ID
- Executes compiled LangGraph investigation loop
- Persists final `InvestigationResult` to PostgreSQL `investigations` table
- Acknowledges stream message (`XACK`) only upon successful persistence

### AI Investigation Agent (`agent/graph.py`, `agent/nodes/`)

- Explicit LangGraph StateGraph topology
- Bounded verification loop (`max_iterations = 3`)
- Nodes: `incident_intake`, `build_investigation_plan`, `collect_evidence`, `analyze_evidence`, `diagnose`, `verify_diagnosis`, `finalize`
- Communicates exclusively via structured typed models

### Telemetry Evidence Capability (`capabilities/evidence/`)

- Implements `TelemetryEvidenceProvider` protocol over `OperationalStore`
- Capability abstraction preventing LLM/Agent nodes from executing raw SQL or touching Redis directly
- Methods: `query_recent_telemetry`, `compare_telemetry_baseline`, `get_incident_trigger_context`

### Simulator (`simulator/runner.py`)

- Emits healthy → failure scenario through both adapters
- 2-second intervals
- Uses actual Redis EventBus

## Data Flow: Telemetry Ingestion

```
raw_payload
    → Adapter.normalize()
    → TelemetryRecord
    → TelemetryReceivedEvent
    → EventBus.publish_telemetry()   [Redis XADD]
    → [Worker picks up via XREADGROUP]
    → Store.save_telemetry()         [PostgreSQL INSERT ON CONFLICT DO NOTHING]
    → EventBus.ack_telemetry()       [Redis XACK]
```

## Data Flow: Incident Detection

```
Detection loop wakes (every 10s)
    → For each rule:
        → Store.query_recent_metrics(service, metric, since)
        → evaluate_rule(rule, records) → EvaluationResult
        → if result.fired:
            → Store.get_active_episode(episode_key) → existing?
            → if no existing: create Incident
                → Store.save_incident(incident)
                → EventBus.publish_incident(IncidentCreatedEvent)
```

## Data Flow: AI Incident Investigation

```
Orchestrator consumes IncidentCreatedEvent [Redis XREADGROUP sentinel:incidents]
    → LangGraph ainvoke(initial_state, config={thread_id: incident_id})
        → incident_intake (validates incident, starts clock)
        → build_investigation_plan (synthesizes structured InvestigationPlan)
        → collect_evidence (queries TelemetryEvidenceProvider)
        → analyze_evidence (formulates Hypotheses citing evidence IDs)
        → diagnose (synthesizes Diagnosis citing supporting evidence)
        → verify_diagnosis (verifies evidence sufficiency & confidence)
            → if unverified and iter < 3: loop to collect_evidence
            → if verified or iter >= 3: route to finalize
        → finalize (constructs durable InvestigationResult)
    → Store.save_investigation(result) [PostgreSQL INSERT ON CONFLICT DO UPDATE]
    → EventBus.ack_incident() [Redis XACK]
```

## Dependency Graph

```
domain/models  ←── domain/contracts (Protocol only)
     ↑                    ↑
     │                    │
integrations/     storage/      detection/     api/     simulator/
(adapters, bus)   (postgres)    (rules, loop)  (fastapi) (runner)
```

The domain layer has no external dependencies (except Pydantic).
Adapters depend only on domain models.
Core pipeline depends only on domain contracts (Protocols).

## Current Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| Domain models | Pydantic v2 |
| API | FastAPI + uvicorn |
| EventBus | Redis Streams (redis-py async) |
| OperationalStore | PostgreSQL + SQLAlchemy async + asyncpg |
| Rules | YAML |
| Logging | structlog |
| Configuration | pydantic-settings (env vars) |
| Tests | pytest + pytest-asyncio |
| Infrastructure | Docker Compose |

## Failure Modes

| Failure | Behaviour |
|---|---|
| Redis unavailable | Worker exits with error; messages not lost (stream persists) |
| PostgreSQL unavailable | Worker retries; messages stay in PEL |
| Adapter parse error | Logged; message NOT acked (stays in PEL) |
| Duplicate telemetry_id | PostgreSQL ON CONFLICT DO NOTHING; idempotent |
| Detection loop error | Logged; loop continues after sleep |
| Active episode exists | New incident NOT created; logged at DEBUG |

## Current Limitations

- Worker does not implement PEL recovery (stale/failed messages) — future slice
- Detection loop discovers services only via `service_filter` in rules — future: auto-discover from store
- No trace/log adapters implemented
- No retry/circuit-breaker on store or bus clients
- Integration tests require Docker Compose to be running
