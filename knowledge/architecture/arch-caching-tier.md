---
document_id: arch-005
document_type: architecture
title: Caching Tier Architecture and Invalidation Strategy
service: shared-cache
environment: production
severity: medium
version: 1
---
# Caching Tier Architecture and Invalidation Strategy

## Overview
Two-tier caching: Local in-memory LRU cache on application pods (L1) and shared Redis cluster (L2).
TTL standards: User profiles (15m), Product catalog (60m), Session tokens (24h).\n