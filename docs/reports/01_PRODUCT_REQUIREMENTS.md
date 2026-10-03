# SentinelOps — Product Requirements

## Current Implementation Scope

This document covers the requirements for Slice 1 only. Requirements for subsequent slices are defined in the master specification.

## Slice 1 Requirements

### Functional Requirements

1. **FR-001:** Accept telemetry from at least two structurally different external formats.
2. **FR-002:** Normalize external telemetry into a single canonical domain model.
3. **FR-003:** Publish canonical telemetry to a persistent, ordered event bus.
4. **FR-004:** Persist canonical telemetry to a queryable operational store.
5. **FR-005:** Evaluate configurable threshold rules against canonical stored metrics.
6. **FR-006:** Create a canonical incident when a rule fires for the first time in an episode.
7. **FR-007:** Avoid creating duplicate incidents while the same condition remains active.
8. **FR-008:** Publish incident events to the incident event bus.
9. **FR-009:** Expose incidents via an HTTP API.
10. **FR-010:** Emit a simulated failure scenario for demonstration.

### Non-Functional Requirements

1. **NFR-001 (Provider neutrality):** The core pipeline must not branch on telemetry provider.
2. **NFR-002 (Determinism):** Detection must be deterministic; no LLM or ML model in the detection layer.
3. **NFR-003 (Idempotency):** Replaying the same telemetry event must not create duplicate records.
4. **NFR-004 (Observability):** All components must use structured logging.
5. **NFR-005 (Configurability):** No business logic values (thresholds, service names) hardcoded; all in config files or environment variables.
6. **NFR-006 (Testability):** The detection engine must be testable without infrastructure.

### Out of Scope for Slice 1

- LLM-based investigation
- RAG / knowledge retrieval
- Remediation actions
- Policy engine / approval workflow
- AWS / cloud deployment
- Frontend / UI
- Multi-tenant or authentication
- Production-grade security
