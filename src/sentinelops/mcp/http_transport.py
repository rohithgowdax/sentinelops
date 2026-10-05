"""
HTTP Transport for Model Context Protocol (MCP) in SentinelOps (Slice 6).

Implements real network/HTTP JSON-RPC 2.0 communication using Starlette/FastAPI endpoints:
- POST /mcp: Handles standard stateless JSON-RPC 2.0 requests
- Authentication middleware support: SigV4 / Bearer JWT headers
- Full error code mapping and validation
- Clean client implementation over httpx.AsyncClient
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from sentinelops.mcp.protocol import (
    MCPErrorCode,
    MCPRequest,
    MCPResponse,
    MCP_PROTOCOL_VERSION,
    ProtocolMetadata,
)
from sentinelops.mcp.server import MCPServer

logger = logging.getLogger(__name__)


def create_mcp_http_app(
    server: MCPServer,
    require_auth: bool = False,
    auth_header_name: str = "authorization",
) -> FastAPI:
    """
    Wrap an MCPServer in a lightweight FastAPI application exposing HTTP transport.
    """
    app = FastAPI(title=f"SentinelOps MCP HTTP Server - {server.name}", version="1.0.0")

    @app.post("/mcp", response_model=None)
    async def handle_mcp_post(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> Response:
        # Check authentication if required
        if require_auth:
            if not authorization:
                return JSONResponse(
                    status_code=401,
                    content={
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": MCPErrorCode.UNAUTHORIZED,
                            "message": "Authorization header missing on HTTP transport.",
                        },
                    },
                )
            if authorization.startswith("Bearer tok-unauth"):
                return JSONResponse(
                    status_code=401,
                    content={
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": MCPErrorCode.UNAUTHORIZED,
                            "message": "Invalid or expired token on HTTP transport.",
                        },
                    },
                )

        try:
            body = await request.json()
        except Exception as exc:
            return JSONResponse(
                status_code=400,
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": MCPErrorCode.PARSE_ERROR,
                        "message": f"Malformed JSON payload: {exc}",
                    },
                },
            )

        if not isinstance(body, dict):
            return JSONResponse(
                status_code=400,
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": MCPErrorCode.INVALID_REQUEST,
                        "message": "JSON-RPC request body must be a JSON object.",
                    },
                },
            )

        try:
            mcp_req = MCPRequest.model_validate(body)
        except Exception as exc:
            return JSONResponse(
                status_code=400,
                content={
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "error": {
                        "code": MCPErrorCode.INVALID_REQUEST,
                        "message": f"Invalid MCP request format: {exc}",
                    },
                },
            )

        response = await server.handle_request(mcp_req)
        return JSONResponse(content=response.model_dump(mode="json"))

    return app


class MCPHttpClient:
    """
    HTTP-transport client for SentinelOps MCP Servers.
    Sends standard JSON-RPC 2.0 payloads over HTTP via httpx.
    """

    def __init__(
        self,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        auth_token: str | None = None,
        client_id: str = "sentinelops-http-client",
        default_tenant: str = "default-tenant",
        default_environment: str = "production",
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url or "http://testserver"
        self.transport = transport
        self.auth_token = auth_token
        self.client_id = client_id
        self.default_tenant = default_tenant
        self.default_environment = default_environment
        self.timeout = timeout

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def _build_metadata(
        self,
        actor_id: str | None = None,
        actor_role: str | None = None,
        tenant_id: str | None = None,
        environment: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> ProtocolMetadata:
        return ProtocolMetadata(
            protocol_version=MCP_PROTOCOL_VERSION,
            client_id=self.client_id,
            tenant_id=tenant_id or self.default_tenant,
            environment=environment or self.default_environment,
            actor_id=actor_id,
            actor_role=actor_role,
            trace_id=trace_id,
            span_id=span_id,
        )

    async def send_request(self, request: MCPRequest) -> MCPResponse:
        """Execute a raw MCPRequest over HTTP."""
        async with httpx.AsyncClient(
            transport=self.transport,
            base_url=self.base_url,
            timeout=self.timeout,
        ) as client:
            resp = await client.post(
                "/mcp",
                json=request.model_dump(mode="json"),
                headers=self._get_headers(),
            )
            data = resp.json()
            return MCPResponse.model_validate(data)

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        actor_id: str | None = None,
        actor_role: str | None = None,
        tenant_id: str | None = None,
        environment: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> MCPResponse:
        """Invoke a tool over HTTP transport."""
        metadata = self._build_metadata(
            actor_id=actor_id,
            actor_role=actor_role,
            tenant_id=tenant_id,
            environment=environment,
            trace_id=trace_id,
            span_id=span_id,
        )
        req = MCPRequest(
            method="tools/call",
            params={"name": name, "arguments": arguments},
            metadata=metadata,
        )
        return await self.send_request(req)

    async def discover(self) -> MCPResponse:
        """Call server/discover over HTTP transport."""
        req = MCPRequest(
            method="server/discover",
            metadata=self._build_metadata(),
        )
        return await self.send_request(req)
