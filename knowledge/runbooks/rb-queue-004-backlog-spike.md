---
document_id: rb-queue-004
document_type: runbook
title: Message Broker Queue Backlog and Worker Lag
service: order-service
environment: production
severity: medium
version: 1
---
# Message Broker Queue Backlog and Worker Lag

## Symptoms
- Consumer lag exceeds 50,000 messages.
- Queue publish rate exceeds consume rate by > 3x.
- End-to-end event processing delay increases.

## Diagnostic Steps
1. Measure consumer worker processing time per event.
2. Check for poison pill messages triggering continuous retries.
3. Verify Redis/Kafka cluster broker disk and CPU utilization.

## Resolution
1. Scale horizontal pod autoscaler (HPA) replica count.
2. Move failing poison pill messages to Dead Letter Queue (DLQ).\n