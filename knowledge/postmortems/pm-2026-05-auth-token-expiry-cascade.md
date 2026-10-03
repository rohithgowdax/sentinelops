---
document_id: pm-2026-05
document_type: postmortem
title: Post-Mortem Incident INC-2026-05 Auth Key Rotation Failure
service: auth-service
environment: production
severity: high
version: 1
---
# Post-Mortem: Auth Key Rotation Failure

## Date
2026-03-12

## Impact
35% of API requests rejected with 401 Unauthorized for 18 minutes.

## Root Cause
Automated JWT signing key rotation rotated the private signing key in auth-service before the new public verification key was propagated to edge ingress proxies.

## Resolution
Propagated JWKS cache immediately and adjusted key overlap retention window from 5 minutes to 24 hours.\n