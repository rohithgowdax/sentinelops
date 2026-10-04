# Slice 5: Model Context Protocol (MCP) Interoperability

**Status:** IMPLEMENTED & VERIFIED  
**Date:** October 2026  
**Protocol Revision:** `2026-07-28`  
**Compliance Level:** Strict JSON-RPC 2.0 with Stateless Context Propagation  

---

## 1. Architectural Philosophy: MCP as an Interoperability Layer

In SentinelOps, the Model Context Protocol (MCP) is strictly an **interoperability layer**, not a replacement or bypass for internal core interfaces, domain contracts, or safety policy boundaries.

```text
External Consumer / Host (e.g. AWS AgentCore, Claude Desktop, Cursor)
                              │
                    JSON-RPC 2.0 (MCP 2026-07-28)
                              ▼
           ┌────────────────────────────────────────┐
           │        SentinelOps MCP Servers         │
           │  (Telemetry, Knowledge, Change, Remed.)│
           └──────────────────┬─────────────────────┘
                              │
               Provider-Neutral Capability Interfaces
                              ▼
           ┌────────────────────────────────────────┐
           │          Policy & Safety Gate          │
           │    (PolicyEngine & ApprovalService)    │
           └──────────────────┬─────────────────────┘
                              │
                      Action Execution
                              ▼
                  Provider Implementations
                 (Docker, K8s, CloudWatch, Qdrant)
```

### Safety Invariants Enforced over MCP
1. **Zero Authorization Shortcut:** Calling `execute_action` over MCP does not bypass policy. It strictly invokes `PolicyEngine.evaluate()`. If the policy returns `DENY`, 0 provider executions occur and an error is returned.
2. **Mandatory Human-in-the-Loop (HITL):** If policy evaluation yields `REQUIRES_APPROVAL`, execution is refused with `-32001 (PRECONDITION_FAILED)` unless a valid, unconsumed approval token is supplied.
3. **Actor & Tenant Isolation:** Every request propagates `tenant_id`, `actor_id`, `actor_role`, and `environment`. Cross-tenant or role-violating actions are blocked before execution.

---

## 2. MCP Protocol Implementation (`2026-07-28` Revision)

SentinelOps implements the `2026-07-28` MCP specification natively using Pydantic v2 schemas:

* **Protocol Version:** `2026-07-28`
* **JSON-RPC Version:** `2.0`
* **Transport:** Stateless in-memory / stdio / HTTP-SSE compatible
* **Context Propagation:** `ProtocolMetadata` on every payload:
  * `client_id`, `session_id`, `trace_id` (W3C standard), `tenant_id`, `environment`, `actor_id`, `actor_role`
* **Discovery Caching:** `server/discover` returns `DiscoveryResult` with explicit `CacheHint(ttl_seconds, cache_key, etag)` to eliminate redundant discovery handshakes.
* **Multi-Round-Trip Elicitation:** `client/elicit` allows servers to request structured interactive parameter clarifications from the caller.

---

## 3. Registered MCP Servers and Capabilities

SentinelOps exposes 4 modular, single-responsibility MCP servers:

| MCP Server | Exposed Tools | Exposed Resources | Safety Classification |
|---|---|---|---|
| **`sentinelops-telemetry`** | `query_metrics`<br>`query_logs`<br>`get_service_health`<br>`get_dependencies` | `sentinel://services/{service_id}` | Read-Only (Safe) |
| **`sentinelops-knowledge`** | `search_knowledge`<br>`get_document`<br>`get_evidence` | `sentinel://knowledge/{doc_id}` | Read-Only (Safe) |
| **`sentinelops-change`** | `list_recent_changes`<br>`get_deployment`<br>`get_resource_version` | `sentinel://deployments/{service_id}` | Read-Only (Safe) |
| **`sentinelops-remediation`** | `propose_action`<br>`execute_action` | `sentinel://incidents/{incident_id}`<br>`sentinel://approvals/{action_id}` | Mutating (Gated by Policy Engine & Approval Token) |

---

## 4. MCP Performance Benchmark Results

Direct in-process invocation vs. MCP protocol overhead was empirically benchmarked ($N=50$ iterations per tool):

| Tool Name | Direct Latency (ms) | MCP Latency (ms) | Protocol Overhead (ms) |
|---|---|---|---|
| `query_metrics` | 0.0004 ms | 0.0223 ms | **+0.0219 ms** (~22 µs) |
| `search_knowledge` | 0.2038 ms | 0.2217 ms | **+0.0179 ms** (~18 µs) |
| `get_service_health` | 0.0004 ms | 0.0094 ms | **+0.0090 ms** (~9 µs) |

**Conclusion:** The MCP transport layer introduces less than **25 microseconds** of overhead per tool call, which is negligible compared to model reasoning and network I/O.

---

## 5. Security & Isolation Verification

The security suite (`tests/security/test_mcp_security.py`) formally verifies:
* **Tool Name Confusion & Collision Resistance:** Servers reject calls to undeclared tools or wrong servers (`METHOD_NOT_FOUND`).
* **Input Tampering & Validation:** Invalid argument schemas trigger `-32602 (INVALID_PARAMS)` before any internal handler executes.
* **Unauthorized Caller Role Rejection:** Viewer roles attempting `execute_action` are rejected with `PERMISSION_DENIED`.
* **Prompt Injection Defense:** Malicious instructions embedded in query parameters are treated as literal text and do not hijack the execution path.
* **Strict Policy Invariants:**
  * Policy `DENY` guarantees **zero** downstream provider executions.
  * Policy `REQUIRES_APPROVAL` guarantees **zero** downstream provider executions without an approved token.
