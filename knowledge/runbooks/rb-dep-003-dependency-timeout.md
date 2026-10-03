---
document_id: rb-dep-003
document_type: runbook
title: Downstream Dependency Latency and Timeout Cascade
service: payments-service
environment: production
severity: high
version: 1
---
# Downstream Dependency Latency and Timeout Cascade

## Symptoms
- `http.error_rate` spikes above 0.15 on payments-service.
- Outgoing HTTP client timeouts to third-party payment gateway (`gateway.acme-pay.internal`).
- Circuit breaker trip events reported in logs.

## Diagnostic Steps
1. Check p99 latency for outgoing RPC/HTTP calls.
2. Inspect external partner status dashboards.
3. Verify if connection pool for client HTTP sessions is depleted.

## Root Cause
Third-party payment gateway latency degrading, causing worker thread pool starvation.

## Resolution
1. Trigger circuit breaker fallback mode to queue requests.
2. Switch payment gateway traffic to secondary provider (`gateway-backup`).
3. Notify incident command and update status page.\n