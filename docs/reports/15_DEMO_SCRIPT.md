# SentinelOps — Demo Script

## Overview

This script demonstrates the complete SentinelOps slice 1 pipeline from clean startup to incident detection.

## Step 1: Start Infrastructure

```bash
cd sentinelops
docker compose up -d postgres redis
docker compose ps   # wait until both show (healthy)
```

## Step 2: Start Application Services

**In separate terminals or with `tmux`:**

```bash
# Terminal A — Worker
PYTHONPATH=src python3 -m sentinelops.ingestion.worker

# Terminal B — Detector
PYTHONPATH=src python3 -m sentinelops.detection.runner

# Terminal C — API
PYTHONPATH=src python3 -m sentinelops.api.main
```

## Step 3: Verify API is Up

```bash
curl http://localhost:8000/health
# → {"status":"ok","service":"sentinelops","uptime_seconds":3.1}
```

## Step 4: Run the Simulator

```bash
# Terminal D — Simulator
PYTHONPATH=src python3 -m sentinelops.simulator.runner
```

**Expected output:**
```
simulator.started         service=payments-service
simulator.phase_start     phase=healthy            duration_seconds=30
simulator.otel.emitted    phase=healthy            error_rate=0.0142
simulator.custom.emitted  phase=healthy            err_pct=1.42
...
simulator.phase_start     phase=failure_onset      duration_seconds=20
simulator.otel.emitted    phase=failure_onset      error_rate=0.1923
simulator.custom.emitted  phase=failure_onset      err_pct=19.23
...
```

## Step 5: Watch Detection Fire

In Terminal B (detector), watch for:
```
detection_loop.incident_created  incident_id=INC-A1B2C3D4  rule_id=rule-001-elevated-service-errors  service=payments-service  observed=0.19  severity=critical
```

## Step 6: Retrieve the Incident via API

```bash
curl http://localhost:8000/incidents | python3 -m json.tool
```

```json
[
  {
    "incident_id": "INC-A1B2C3D4",
    "severity": "critical",
    "status": "open",
    "service_name": "payments-service",
    "environment": "production",
    "trigger_rule_id": "rule-001-elevated-service-errors",
    "title": "[CRITICAL] Elevated Service Error Rate on payments-service",
    "episode_key": "rule-001-elevated-service-errors::payments-service::production",
    "initial_evidence": [...]
  }
]
```

## Step 7: Verify Deduplication

The simulator runs for ~70 seconds with sustained failure. The detector runs every 10 seconds. After the first incident is created, subsequent detection cycles find the active episode and do NOT create duplicates.

```bash
curl http://localhost:8000/incidents | python3 -c "import sys,json; data=json.load(sys.stdin); print(f'{len(data)} incident(s) created')"
# → 1 incident(s) created  (NOT one per detection cycle)
```

## Step 8: Clean Up

```bash
docker compose down -v
```

## One-Command Demo (Docker Compose)

```bash
cd sentinelops
docker compose up --build
# Wait for services to start (watch logs)
docker compose --profile demo run --rm simulator
# Check incidents:
curl http://localhost:8000/incidents | python3 -m json.tool
```
