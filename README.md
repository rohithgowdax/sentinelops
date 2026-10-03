# SentinelOps

AI-native incident intelligence and controlled remediation platform.

> **Current status:** Slice 1 — Telemetry Ingestion + Deterministic Detection Pipeline

---

## What SentinelOps Is

SentinelOps is a provider-agnostic incident intelligence and controlled remediation engine. Its core lifecycle is:

```
Observe
→ detect/receive incident
→ investigate
→ correlate evidence
→ generate hypotheses
→ verify hypotheses
→ plan remediation
→ apply policy
→ approve when required
→ execute bounded action
→ verify recovery
→ resolve or re-investigate
```

The system is designed so the LLM/agent investigates incidents, but the detection layer is deterministic, and all remediation actions flow through a policy engine — the LLM never directly executes a production action.

## What This POC Currently Proves

This is **Slice 1** of a phased implementation. It proves one architectural claim:

> *Two different external telemetry formats can enter through different adapters, become the same canonical domain model, and be processed by the exact same detection pipeline — with no provider-specific branching in the core.*

Concretely:
- **Adapter A (OTel-like JSON)** and **Adapter B (custom JSON)** produce semantically equivalent canonical `TelemetryRecord` objects
- The same configurable threshold detection rules fire identically for records from either adapter
- A canonical `Incident` is created deterministically and published to the incident event bus
- The API serves the incident

## What Is NOT Implemented

- LLM-based investigation (Slice 2)
- RAG / knowledge retrieval (Slice 3)
- Policy engine and human approval (Slice 4)
- Remediation actions (Slice 4+)
- MCP server
- AWS deployment
- Frontend / UI
- Authentication / multi-tenancy

## Architecture

```
OTel-like Source          Custom JSON Source
       │                         │
  Adapter A                  Adapter B
       │                         │
       └──────────┬──────────────┘
                  │
         TelemetryRecord (canonical)
                  │
          Redis Streams (sentinel:telemetry)
                  │
         Telemetry Worker
                  │
         PostgreSQL (OperationalStore)
                  │
         Detection Engine (configurable rules, YAML)
                  │
         Canonical Incident
                  │
         Redis Streams (sentinel:incidents)
                  │
         FastAPI (/health, /incidents, /incidents/{id})
```

## Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| Domain models | Pydantic v2 |
| API | FastAPI + uvicorn |
| EventBus | Redis Streams |
| OperationalStore | PostgreSQL + SQLAlchemy async + asyncpg |
| Detection rules | YAML |
| Logging | structlog |
| Configuration | pydantic-settings (env vars) |
| Tests | pytest + pytest-asyncio |
| Infrastructure | Docker Compose |

## Quick Start

### Prerequisites

- Docker Desktop with Compose v2
- Python 3.11+

### Install

```bash
cd sentinelops
pip install -e ".[dev]"
```

### Run Infrastructure

```bash
docker compose up -d postgres redis
```

### Run Services (Development)

```bash
# Three terminals from sentinelops/

# 1. Worker
PYTHONPATH=src python3 -m sentinelops.ingestion.worker

# 2. Detector
PYTHONPATH=src python3 -m sentinelops.detection.runner

# 3. API
PYTHONPATH=src python3 -m sentinelops.api.main
```

### Run Demo Scenario

```bash
PYTHONPATH=src python3 -m sentinelops.simulator.runner
```

Then:
```bash
curl http://localhost:8000/incidents | python3 -m json.tool
```

### Full Docker Compose Demo

```bash
docker compose up --build
docker compose --profile demo run --rm simulator
curl http://localhost:8000/incidents | python3 -m json.tool
```

## Tests

### Unit + Contract Tests (no infrastructure needed)

```bash
cd sentinelops
PYTHONPATH=src python3 -m pytest tests/unit/ tests/contract/ -v
```

**Result: 85 passed, 0 failed**

### Integration Tests (requires running infrastructure)

```bash
docker compose up -d postgres redis
PYTHONPATH=src python3 -m pytest tests/integration/ -v -m integration
```

## Repository Structure

```
sentinelops/
├── src/
│   └── sentinelops/
│       ├── domain/
│       │   ├── models/          # Canonical domain types (provider-neutral)
│       │   └── contracts/       # Protocol interfaces
│       ├── integrations/
│       │   ├── telemetry/
│       │   │   ├── otel_like/   # Adapter A
│       │   │   └── custom_json/ # Adapter B
│       │   └── event_bus/       # Redis Streams implementation
│       ├── ingestion/           # Telemetry worker
│       ├── detection/           # Rule engine + detection loop
│       ├── storage/             # PostgreSQL store
│       ├── api/                 # FastAPI endpoints
│       ├── config/              # Settings (pydantic-settings)
│       └── simulator/           # Scenario simulator
├── tests/
│   ├── unit/                    # No infrastructure required
│   ├── integration/             # Requires Redis + PostgreSQL
│   └── contract/                # Generalization proof tests
├── docs/reports/                # Architecture and decision documents
├── config/
│   └── detection_rules.yaml     # Rule configuration
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── .env.example
```

## Key Design Decisions

See [`docs/reports/13_ARCHITECTURE_DECISIONS.md`](docs/reports/13_ARCHITECTURE_DECISIONS.md) for the full ADR log.

Key decisions:
- **Provider-neutral canonical model** — no vendor field names in the core
- **Redis Streams with consumer groups** — at-least-once delivery, explicit ACK
- **Deterministic detection** — YAML rules, pure evaluation function, no LLM in detection
- **Episode-key deduplication** — persistent deduplication survives process restarts

## Current Test Status

| Suite | Tests | Status |
|---|---|---|
| Unit tests | 69 | ✅ 69/69 passed |
| Contract tests | 13 | ✅ 13/13 passed (generalization proof) |
| Integration tests | ~8 | ⏳ Written, require infrastructure to run |
| **Total** | **85+** | **✅ Unit+contract clean** |

## Next Slice

Slice 2 will attach the LangGraph orchestrator to the `sentinel:incidents` stream for AI-powered incident investigation. It will NOT modify the detection pipeline.
