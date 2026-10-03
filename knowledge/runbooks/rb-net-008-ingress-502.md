---
document_id: rb-net-008
document_type: runbook
title: Ingress Controller Bad Gateway 502 Failures
service: api-gateway
environment: production
severity: high
version: 1
---
# Ingress Controller Bad Gateway 502 Failures

## Symptoms
- External users receiving 502 Bad Gateway from NGINX/Envoy ingress.
- Upstream connection reset errors.

## Diagnostic Steps
1. Check backend service endpoint availability: `kubectl get endpoints`.
2. Inspect keepalive timeout mismatch between ingress (65s) and upstream (60s).

## Resolution
1. Align keepalive timeout on ingress to be lower than upstream server keepalive.
2. Restart unhealthy backend service endpoints.\n