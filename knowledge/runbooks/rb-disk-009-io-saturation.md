---
document_id: rb-disk-009
document_type: runbook
title: Storage IOPS Saturation and Disk Latency
service: database-cluster
environment: production
severity: critical
version: 1
---
# Storage IOPS Saturation and Disk Latency

## Symptoms
- Database write latency exceeds 100ms.
- EBS volume burst balance depleted to 0%.

## Diagnostic Steps
1. Check AWS CloudWatch / disk volume queue length.
2. Identify queries triggering large disk temporary tables.

## Resolution
1. Modify EBS volume to provisioned IOPS (gp3/io2).
2. Kill unindexed queries sorting large result sets on disk.\n