# SentinelOps — Retrieval Architecture

**Status: NOT IMPLEMENTED IN SLICE 1**

This document will be written when slice 3 (RAG / knowledge retrieval) is implemented.

## Planned for Slice 3

- Vector store integration (provider TBD)
- Runbook and knowledge base indexing
- Semantic search over historical incidents
- Retrieval-augmented investigation context

## Architectural Invariants (Pre-Defined)

1. RAG retrieval is a tool available to the agent — not a core pipeline component.
2. Retrieved context must be traceable (source document, chunk, score).
3. The retrieval layer must not modify incidents or telemetry.
