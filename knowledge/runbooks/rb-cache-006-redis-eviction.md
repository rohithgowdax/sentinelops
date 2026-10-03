---
document_id: rb-cache-006
document_type: runbook
title: Redis Cache Eviction and Memory Saturation
service: shared-cache
environment: production
severity: medium
version: 1
---
# Redis Cache Eviction and Memory Saturation

## Symptoms
- `redis.evicted_keys` rate surges.
- Database read load increases by 200% due to cache misses (cache stampede).
- Redis memory usage hits `maxmemory` limit.

## Diagnostic Steps
1. Inspect `INFO memory` on Redis cluster.
2. Identify keys with missing TTLs via `redis-cli --bigkeys`.
3. Check eviction policy (`volatile-lru` vs `allkeys-lru`).

## Resolution
1. Increase Redis memory allocation or cluster shard count.
2. Add missing TTLs to unbounded cache writes.\n