---
document_id: arch-004
document_type: architecture
title: Event Streaming and Message Broker Topology
service: message-broker
environment: production
severity: high
version: 1
---
# Event Streaming and Message Broker Topology

## Overview
Combines Redis Streams for fast operational event coordination (SentinelOps telemetry & incidents) and Kafka for high-throughput transactional audit logs.\n