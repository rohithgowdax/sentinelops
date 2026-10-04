"""
Model Context Protocol (MCP) Client for SentinelOps (Revision 2026-07-28).

Provides:
- In-process or transport-backed dispatch to MCP servers
- Context propagation (actor, tenant, environment, trace_id)
- Discovery caching based on server-provided CacheHint
- Multi-round-trip elicitation handling
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sentinelops.mcp.protocol import (
    DiscoveryResult,
    MCPRequest,
    MCPResponse,
    MCP_PROTOCOL_VERSION,
    ProtocolMetadata,
    ResourceDefinition,
    ToolDefinition,
)
from sentinelops.mcp.server import MCPServer

logger = logging.getLogger(__name__)


class MCPClient:
    """
    Stateless MCP Client implementing revision 2026-07-28.
    """

    def __init__(
        self,
        server: MCPServer,
        client_id: str = "sentinelops-agent-client",
        default_tenant: str = "default-tenant",
        default_environment: str = "production",
    ) -> None:
        self.server = server
        self.client_id = client_id
        self.default_tenant = default_tenant
        self.default_environment = default_environment

        self._cached_discovery: DiscoveryResult | None = None
        self._cached_tools: list[ToolDefinition] | None = None
        self._cached_resources: list[ResourceDefinition] | None = None
        self._cache_expiry: datetime | None = None

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

    async def discover(self, refresh: bool = False) -> DiscoveryResult:
        """Call 'server/discover' to retrieve server metadata and capabilities."""
        now = datetime.now(tz=timezone.utc)
        if not refresh and self._cached_discovery and self._cache_expiry and now < self._cache_expiry:
            return self._cached_discovery

        req = MCPRequest(
            method="server/discover",
            metadata=self._build_metadata(),
        )
        resp = await self.server.handle_request(req)
        if resp.error:
            raise RuntimeError(f"Discovery failed on server '{self.server.name}': {resp.error.message}")

        discovery = DiscoveryResult.model_validate(resp.result)
        self._cached_discovery = discovery
        # Apply cache hint TTL
        ttl = discovery.cache_hint.max_age_seconds
        self._cache_expiry = datetime.fromtimestamp(now.timestamp() + ttl, tz=timezone.utc)
        return discovery

    async def list_tools(self, refresh: bool = False) -> list[ToolDefinition]:
        """Discover available tools on the MCP server."""
        if not refresh and self._cached_tools is not None:
            return self._cached_tools

        req = MCPRequest(
            method="tools/list",
            metadata=self._build_metadata(),
        )
        resp = await self.server.handle_request(req)
        if resp.error:
            raise RuntimeError(f"Listing tools failed: {resp.error.message}")

        tools_data = resp.result.get("tools", [])
        self._cached_tools = [ToolDefinition.model_validate(t) for t in tools_data]
        return self._cached_tools

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
        """Invoke a tool on the MCP server with full context propagation."""
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
        return await self.server.handle_request(req)

    async def list_resources(self) -> list[ResourceDefinition]:
        """List exposed read-only resources."""
        req = MCPRequest(
            method="resources/list",
            metadata=self._build_metadata(),
        )
        resp = await self.server.handle_request(req)
        if resp.error:
            raise RuntimeError(f"Listing resources failed: {resp.error.message}")

        resources_data = resp.result.get("resources", [])
        return [ResourceDefinition.model_validate(r) for r in resources_data]

    async def read_resource(
        self,
        uri: str,
        actor_id: str | None = None,
        actor_role: str | None = None,
        tenant_id: str | None = None,
        environment: str | None = None,
    ) -> MCPResponse:
        """Read a specific operational resource by URI."""
        metadata = self._build_metadata(
            actor_id=actor_id,
            actor_role=actor_role,
            tenant_id=tenant_id,
            environment=environment,
        )
        req = MCPRequest(
            method="resources/read",
            params={"uri": uri},
            metadata=metadata,
        )
        return await self.server.handle_request(req)
