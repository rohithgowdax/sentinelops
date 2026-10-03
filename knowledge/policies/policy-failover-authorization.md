---
document_id: pol-002
document_type: policy
title: Automated and Manual Failover Authorization Protocol
service: platform
environment: production
severity: critical
version: 1
---
# Automated and Manual Failover Authorization Protocol

## Policy Rules
1. Automated database failover is permitted only when primary node heartbeat is lost for > 30 seconds.
2. Cross-region traffic redirection requires two authorized on-call engineers.\n