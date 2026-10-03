---
document_id: rb-db-001
document_type: runbook
title: PostgreSQL Connection Pool Exhaustion Troubleshooting
service: payments-service
environment: production
severity: critical
version: 2
---
# PostgreSQL Connection Pool Exhaustion Troubleshooting

## Summary
This runbook covers diagnosis and mitigation when backend services exceed available PostgreSQL connection limits.

## Symptoms
- HTTP 500/503 errors on database-dependent endpoints.
- Error logs stating: `FATAL: remaining connection slots are reserved for non-replication superuser connections`.
- Metrics indicate pool active connections == max pool size (e.g. 100/100).
- Latency spike on transactions exceeding 5000ms.

## Diagnostic Steps
1. Inspect `db.pool.active_connections` vs `db.pool.max_connections`.
2. Check PostgreSQL server connections via `SELECT count(*) FROM pg_stat_activity WHERE state = 'active'`.
3. Identify long-running transactions: `SELECT pid, now() - pg_stat_activity.query_start AS duration, query FROM pg_stat_activity WHERE state != 'idle' ORDER BY 2 DESC;`.
4. Inspect recent application releases for missing transaction commits or unclosed sessions.

## Root Cause
Connection leaks caused by unclosed SQLAlchemy/asyncpg sessions or sudden thread pileup during downstream API slowness.

## Resolution
1. Temporarily increase pgbouncer max client connections if database CPU is below 60%.
2. Restart backend worker pods with leaking connections.
3. Roll back any release that introduced connection pooling misconfigurations.\n