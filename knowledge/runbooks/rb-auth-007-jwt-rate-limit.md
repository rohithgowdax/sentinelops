---
document_id: rb-auth-007
document_type: runbook
title: Authentication Service Rate Limiting and Token Validation Failures
service: auth-service
environment: production
severity: high
version: 1
---
# Authentication Service Rate Limiting and Token Validation Failures

## Symptoms
- HTTP 401/403 and 429 response rate spikes on API Gateway.
- Token signing key rotation failures.

## Diagnostic Steps
1. Verify public key JWKS endpoint availability.
2. Check rate limit counters in Redis auth cache.

## Resolution
1. Flush stale JWKS public key cache.
2. Temporarily adjust IP rate limiting thresholds for trusted client proxies.\n