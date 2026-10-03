---
document_id: pm-2026-06
document_type: postmortem
title: Post-Mortem Incident INC-2026-06 Kafka Consumer Rebalance Storm
service: order-service
environment: production
severity: medium
version: 1
---
# Post-Mortem: Kafka Consumer Rebalance Storm

## Date
2026-03-20

## Impact
Order event processing delayed by 35 minutes; queue backlog spiked to 240,000 items.

## Root Cause
GC pauses on heavy batch processing workers exceeded `max.poll.interval.ms` (300,000ms), triggering continuous rebalancing loops across the consumer group.

## Resolution
Increased `max.poll.interval.ms` and reduced batch size from 500 to 50 records per poll.\n