---
document_id: arch-003
document_type: architecture
title: Database Topology and High-Availability Clustering
service: database-cluster
environment: production
severity: critical
version: 1
---
# Database Topology and High-Availability Clustering

## Overview
Primary-standby PostgreSQL 16 cluster with streaming replication managed by Patroni and etcd.

## Capacity Limits
- Maximum connections: 250 (superuser reserved: 10).
- PgBouncer pooling mode: transaction.
- Read replicas: 2 read-only endpoints behind load balancer.\n