# SentinelOps — Runbook (Slice 1)

## Prerequisites

- Docker Desktop (with Compose v2)
- Python 3.11+
- `pip`

## Installation

```bash
# From the project root
cd sentinelops
pip install -e ".[dev]"
```

## Environment Configuration

```bash
cp .env.example .env
# Edit .env if needed (defaults work for local Docker Compose)
```

## Starting Infrastructure

```bash
# From sentinelops/ directory
docker compose up -d postgres redis

# Verify health
docker compose ps
```

Expected output:
```
NAME                  STATUS          PORTS
sentinelops-postgres  running (healthy)  0.0.0.0:5432->5432/tcp
sentinelops-redis     running (healthy)  0.0.0.0:6379->6379/tcp
```

## Running Services Locally (Development)

Open three terminal windows from the `sentinelops/` directory:

**Terminal 1 — Telemetry Worker:**
```bash
PYTHONPATH=src python3 -m sentinelops.ingestion.worker
```

**Terminal 2 — Detection Engine:**
```bash
PYTHONPATH=src python3 -m sentinelops.detection.runner
```

**Terminal 3 — Orchestrator Service (Slice 2 AI Investigation):**
```bash
PYTHONPATH=src python3 -m sentinelops.orchestrator.runner
```

**Terminal 4 — API:**
```bash
PYTHONPATH=src python3 -m sentinelops.api.main
```

## Running the Full Stack with Docker Compose

```bash
docker compose up --build
```

This starts: postgres, redis, worker, detector, orchestrator, api.

## Running the Demo Scenario

```bash
# Start infrastructure + services first, then:
docker compose --profile demo up simulator

# OR run locally:
PYTHONPATH=src python3 -m sentinelops.simulator.runner
```

The simulator emits ~70 seconds of telemetry:
- 0–30s: Healthy (error_rate 1–2%)
- 30–50s: Failure onset (error_rate 18–25%)
- 50–70s: Sustained failure plateau

While the simulator runs:
1. Watch the detector logs for:
```
detection_loop.incident_created  incident_id=INC-XXXXXXXX
```
2. Watch the orchestrator logs for:
```
orchestrator.investigation_completed incident_id=INC-XXXXXXXX status=diagnosed
```

## Verifying the Pipeline

```bash
# Check API health
curl http://localhost:8000/health

# List incidents (should have ≥1 after failure phase)
curl http://localhost:8000/incidents | python3 -m json.tool

# Get specific incident
curl http://localhost:8000/incidents/INC-XXXXXXXX | python3 -m json.tool

# Get AI investigation results for the incident
curl http://localhost:8000/incidents/INC-XXXXXXXX/investigation | python3 -m json.tool
```

## Running Tests

### Unit and Contract Tests (no infrastructure required)

```bash
cd sentinelops
PYTHONPATH=src python3 -m pytest tests/unit/ tests/contract/ -v
```

### Integration Tests (requires Docker Compose services)

```bash
docker compose up -d postgres redis
cd sentinelops
PYTHONPATH=src python3 -m pytest tests/integration/ -v -m integration
```

### All Tests

```bash
cd sentinelops
PYTHONPATH=src python3 -m pytest tests/ -v
```

## Inspecting Redis Streams

```bash
# View telemetry stream entries
docker compose exec redis redis-cli XLEN sentinel:telemetry
docker compose exec redis redis-cli XRANGE sentinel:telemetry - + COUNT 3

# View incident stream
docker compose exec redis redis-cli XLEN sentinel:incidents
docker compose exec redis redis-cli XRANGE sentinel:incidents - +
```

## Inspecting PostgreSQL

```bash
docker compose exec postgres psql -U sentinelops -c "SELECT count(*) FROM telemetry;"
docker compose exec postgres psql -U sentinelops -c "SELECT incident_id, severity, status, service_name, created_at FROM incidents;"
docker compose exec postgres psql -U sentinelops -c "SELECT incident_id, status, confidence, completed_at FROM investigations;"
```

## Stopping

```bash
docker compose down          # stop services, preserve volumes
docker compose down -v       # stop services, delete volumes (fresh start)
```

## Troubleshooting

| Problem | Check |
|---|---|
| Worker can't connect to Redis | `docker compose ps redis` — is it healthy? |
| Detector creates no incidents | Check `PYTHONPATH`, check rules file path, check that metrics are in the DB |
| Orchestrator doesn't investigate | Ensure Redis `sentinel:incidents` has un-ACKed messages; check consumer group |
| API returns 500 | Check `PYTHONPATH=src python3 -m sentinelops.api.main` logs |
| No metrics in DB | Worker may not be running; check worker logs |
| Duplicate incidents | Should not happen; check episode_key in DB: `SELECT episode_key, status FROM incidents;` |

## Key Configuration Variables

| Variable | Default | Description |
|---|---|---|
| `SENTINELOPS_REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `SENTINELOPS_POSTGRES_DSN` | `postgresql+asyncpg://sentinelops:sentinelops@localhost:5432/sentinelops` | PostgreSQL connection |
| `SENTINELOPS_DETECTION_RULES_PATH` | `config/detection_rules.yaml` | Rules file |
| `SENTINELOPS_DETECTION_INTERVAL_SECONDS` | `10.0` | Detection loop interval |
| `SENTINELOPS_ORCHESTRATOR_CONSUMER_GROUP` | `sentinelops-orchestrator` | Orchestrator Redis consumer group |
| `SENTINELOPS_LOG_LEVEL` | `INFO` | Log verbosity |

