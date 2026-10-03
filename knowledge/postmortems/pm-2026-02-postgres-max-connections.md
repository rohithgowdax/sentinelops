---
document_id: pm-2026-02
document_type: postmortem
title: Post-Mortem Incident INC-2026-02 Database Connection Pool Exhaustion
service: payments-service
environment: production
severity: critical
version: 1
---
# Post-Mortem: Database Connection Pool Exhaustion

## Date
2026-02-03

## Impact
Total outage of payments-service for 25 minutes during peak shopping volume.

## Root Cause
A missing session context manager in the checkout webhook handler left database connections open indefinitely. When webhook traffic surged, all 100 pool connections were held open, blocking critical transaction paths.

## Resolution
Restarted application pods to clear connection pool. Deployed bugfix ensuring `async with session.begin():` was used across all handlers.\n