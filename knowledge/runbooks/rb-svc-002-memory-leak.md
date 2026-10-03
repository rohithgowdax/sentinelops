---
document_id: rb-svc-002
document_type: runbook
title: Service Heap Memory Exhaustion and OOMKilled Runbook
service: payments-service
environment: production
severity: high
version: 1
---
# Service Heap Memory Exhaustion and OOMKilled Runbook

## Summary
Guidance for investigating monotonic memory growth leading to container OOMKills.

## Symptoms
- Container restart reason `OOMKilled` (exit code 137).
- `container.memory.usage` climbing steadily until cgroup limit is reached.
- Garbage collection frequency increases dramatically (GC pause > 2000ms).

## Diagnostic Steps
1. Check memory growth profile over a 6-hour lookback window.
2. Verify if memory drops after GC or continues monotonic climb.
3. Check for unbounded in-memory caches or request payload buffering.

## Root Cause
Global dict/cache growth or unclosed streaming responses retaining references in memory.

## Resolution
1. Scale up pod memory limit temporarily to prevent crashloop.
2. Rolling restart deployment to reset heap allocations.
3. Deploy patch with LRU cache eviction bounds.\n