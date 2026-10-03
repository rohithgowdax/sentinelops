---
document_id: rb-jvm-010
document_type: runbook
title: JVM Stop-the-World Garbage Collection Spikes
service: analytics-service
environment: production
severity: medium
version: 1
---
# JVM Stop-the-World Garbage Collection Spikes

## Symptoms
- Application pauses causing healthcheck timeout failures.
- GC pause times exceeding 3000ms in G1GC logs.

## Diagnostic Steps
1. Inspect GC logs: `jstat -gcutil`.
2. Check heap allocation rate and survivor space size.

## Resolution
1. Tune MaxGCPauseMillis parameter.
2. Increase young generation allocation size.\n