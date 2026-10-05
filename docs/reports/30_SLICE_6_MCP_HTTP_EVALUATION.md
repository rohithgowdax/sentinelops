# Slice 6: MCP HTTP Transport Evaluation

**Status:** IMPLEMENTED, TESTED & BENCHMARKED  
**Date:** October 2026  
**Transport:** JSON-RPC 2.0 over HTTP (FastAPI / Starlette + `httpx.AsyncClient`)  

---

## 1. Architectural Implementation

SentinelOps Slice 6 implements network HTTP transport for the Model Context Protocol:
* Server Application: [`create_mcp_http_app()`](file:///Users/rohithgowda/Desktop/Project/sentinelops/src/sentinelops/mcp/http_transport.py) mounts an `MCPServer` instance onto FastAPI.
* Endpoint: `POST /mcp` processes stateless JSON-RPC 2.0 requests with per-request `ProtocolMetadata`.
* Client Adapter: [`MCPHttpClient`](file:///Users/rohithgowda/Desktop/Project/sentinelops/src/sentinelops/mcp/http_transport.py) handles HTTP connection pooling and serialization.
* Perimeter Auth: Optional bearer token enforcement at the HTTP transport layer (`require_auth=True`).

---

## 2. Empirical Transport Benchmark Results

Benchmarked across 50 iterations ($N=50$) with a 5-iteration warmup:

| Operation | Direct Provider | Local MCP Dispatch | MCP over HTTP | MCP over HTTP + Auth |
|---|---|---|---|---|
| `query_metrics` (Mean) | 0.000 ms | 0.020 ms | **0.498 ms** | **0.330 ms** |
| `query_metrics` (p50) | 0.000 ms | 0.017 ms | **0.282 ms** | **0.281 ms** |
| `query_metrics` (p95) | 0.001 ms | 0.032 ms | **0.531 ms** | **0.622 ms** |
| `search_knowledge` (Mean)| 0.220 ms | 0.239 ms | **0.535 ms** | — |
| `search_knowledge` (p50) | 0.212 ms | 0.234 ms | **0.512 ms** | — |
| `search_knowledge` (p95) | 0.248 ms | 0.280 ms | **0.627 ms** | — |

---

## 3. Boundary Security Over HTTP

Formally verified in [`tests/security/test_mcp_http_security.py`](file:///Users/rohithgowda/Desktop/Project/sentinelops/tests/security/test_mcp_http_security.py):
1. **Unauthenticated Request Rejection:** Calls missing Authorization headers are rejected with HTTP 401 and `MCPErrorCode.UNAUTHORIZED`.
2. **Forged Token Rejection:** Calls with invalid bearer tokens are rejected at the transport boundary.
3. **Invariant A:** Policy `DENY` over HTTP produces **0** downstream provider calls.
4. **Invariant B:** Policy `REQUIRES_APPROVAL` over HTTP blocks execution with `APPROVAL_REQUIRED` and produces **0** provider calls.
5. **Invariant C:** Parameter tampering over HTTP fails closed (`ARGUMENT_TAMPERING`); anti-replay check blocks re-use of consumed approval tokens over HTTP.
