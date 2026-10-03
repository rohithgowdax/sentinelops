---
document_id: rb-deploy-005
document_type: runbook
title: Post-Deployment Regression Rollback Procedure
service: payments-service
environment: production
severity: critical
version: 3
---
# Post-Deployment Regression Rollback Procedure

## Symptoms
- Sharp increase in 5xx HTTP responses immediately following a deployment.
- Error rate exceeding 10% within 10 minutes of canary release.

## Diagnostic Steps
1. Compare error rate before deployment vs post-deployment window.
2. Check git commit diff for recently deployed image tag.
3. Verify if database migrations were applied.

## Root Cause
Schema mismatch or unhandled exception in new release code.

## Resolution
1. Execute immediate automated rollback to previous known-stable image tag.
2. Verify error rate returns to baseline (< 0.01) within 3 minutes of rollback.
3. Lock deployment pipeline until post-mortem is complete.\n