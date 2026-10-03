---
document_id: arch-001
document_type: architecture
title: Payments Service Architecture and Topology
service: payments-service
environment: production
severity: high
version: 2
---
# Payments Service Architecture and Topology

## Overview
`payments-service` is an asynchronous Python service handling credit card authorization, capture, and refund processing.

## Dependencies
- Primary Storage: PostgreSQL 16 (connection pool max size 20 per pod, 5 pod replicas = 100 connections).
- Cache / Event Bus: Redis 7.0 for idempotency keys and state tracking.
- Downstream External: `AcmePay` HTTP API (p95 expected latency: 180ms).

## Failure Domains & Mitigations
1. PostgreSQL saturation: circuit-break checkout requests if active connections exceed 85%.
2. AcmePay latency: circuit breaker trips after 5 consecutive timeouts > 2000ms.\n