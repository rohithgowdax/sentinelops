---
document_id: pm-2026-04
document_type: postmortem
title: Post-Mortem Incident INC-2026-04 Release v2.4.0 Regression
service: payments-service
environment: production
severity: critical
version: 1
---
# Post-Mortem: Release v2.4.0 Regression

## Date
2026-03-02

## Impact
HTTP error rate jumped to 28% within 2 minutes of rolling out release v2.4.0 to production.

## Root Cause
Release v2.4.0 introduced a required column `merchant_account_id` in database queries without a corresponding default value for legacy records.

## Resolution
Rolled back immediately to release v2.3.9 using `rb-deploy-005`. Error rate dropped back to 0.002 within 90 seconds.\n