---
document_id: pm-2026-03
document_type: postmortem
title: Post-Mortem Incident INC-2026-03 Redis Cache OOM Eviction Storm
service: shared-cache
environment: production
severity: medium
version: 1
---
# Post-Mortem: Redis Cache OOM Eviction Storm

## Date
2026-02-18

## Impact
Session cache degraded; users experienced intermittent logouts for 15 minutes.

## Root Cause
An analytics batch job wrote millions of session event records into Redis without TTLs, saturating the 16GB memory limit and triggering aggressive key evictions.

## Resolution
Flushed orphaned analytics keys and configured mandatory TTL linting in cache client libraries.\n