---
document_id: pm-2026-01
document_type: postmortem
title: Post-Mortem Incident INC-2026-01 Payment Gateway Cascading Timeouts
service: payments-service
environment: production
severity: high
version: 1
---
# Post-Mortem: Payment Gateway Cascading Timeouts

## Date
2026-01-14

## Impact
Payments service experienced 18% error rate for 42 minutes. 1,420 checkout transactions failed.

## Root Cause
The external payment provider `AcmePay` suffered an infrastructure degradation causing request latencies to jump from 150ms to 9,000ms. Because payments-service had client HTTP timeout configured to 30s instead of 2s, incoming connections saturated the worker thread pool, preventing any other payment requests from completing.

## Action Items
1. Reduced client HTTP timeout to external gateway to 2500ms.
2. Implemented circuit breaker with automated failover to secondary provider.
3. Created detection rule `rule-001-elevated-service-errors` with 0.10 threshold.\n