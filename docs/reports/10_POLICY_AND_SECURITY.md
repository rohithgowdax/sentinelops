# SentinelOps — Policy and Security

**Status: NOT IMPLEMENTED IN SLICE 1**

This document will be written when the policy engine and approval workflow are implemented.

## Architectural Invariants (Pre-Defined)

The policy layer enforces the invariant:

```
LLM
 ↓
ActionRequest
 ↓
Policy Engine
 ↓
Approval (if required)
 ↓
ActionProvider
```

The LLM never directly calls an ActionProvider. This is a hard architectural constraint enforced by the interface design.

## Planned for Slice 4+

- Policy rule evaluation engine
- Risk scoring for ActionRequests
- Human approval workflow (async, with timeout)
- Action audit trail
- Bounded action permissions (scope, duration, blast radius)
