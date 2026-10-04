"""
AWS Bedrock AgentCore Gateway Adapter for SentinelOps (Slice 5C).

Provides:
- Target aggregation: Unifies multiple SentinelOps MCP servers into a single Gateway tool catalog.
- Inbound Authorization: Validates caller IAM tokens or JWT claims at gateway perimeter.
- Outbound Authorization: Maps caller claims into SentinelOps `ActorContext` (preserving RBAC).
- Multi-round-trip elicitation forwarding for Human-in-the-Loop approval requests.

Architectural Rule:
This is an external adapter layer. SentinelOps Core has ZERO dependency on AWS SDKs or boto3.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from sentinelops.domain.models.policy import ActorContext, ActorRole
from sentinelops.mcp.protocol import (
    DiscoveryResult,
    MCPErrorCode,
    MCPRequest,
    MCPResponse,
    MCP_PROTOCOL_VERSION,
    ProtocolMetadata,
    ServerCapabilities,
    ToolDefinition,
)
from sentinelops.mcp.server import MCPServer

logger = logging.getLogger(__name__)


class AgentCoreGatewayAdapter:
    """
    Adapter simulating Amazon Bedrock AgentCore Gateway in MCP target aggregation mode.
    """

    def __init__(
        self,
        gateway_id: str = "gw-sentinelops-prod-01",
        region: str = "us-east-1",
    ) -> None:
        self.gateway_id = gateway_id
        self.region = region
        self._targets: dict[str, MCPServer] = {}  # target_name -> MCPServer
        self._tool_to_target: dict[str, str] = {}  # tool_name -> target_name

    def attach_mcp_target(self, target_name: str, server: MCPServer) -> None:
        """Attach an MCP server as a target in the Gateway catalog."""
        self._targets[target_name] = server
        for tool_name in server._tools:
            self._tool_to_target[tool_name] = target_name
        logger.info("Attached MCP target '%s' to AgentCore Gateway '%s'", target_name, self.gateway_id)

    def verify_inbound_authorization(self, auth_header: str | None) -> tuple[bool, str, dict[str, Any]]:
        """
        Inbound perimeter authorization check.
        Validates bearer token or SigV4 signature format.
        """
        if not auth_header:
            return False, "Missing authorization header", {}

        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            if token.startswith("tok-unauth"):
                return False, "Invalid or expired token", {}
            # Simulated claims extraction
            claims = {
                "sub": "user-sre-lead",
                "role": "incident_commander" if "ic" in token else ("sre" if "sre" in token else "operator"),
                "tenant_id": "tenant-enterprise-alpha",
                "scope": "agentcore:invoke",
            }
            return True, "Authorized", claims
        elif auth_header.startswith("AWS4-HMAC-SHA256"):
            return True, "Authorized via SigV4", {
                "sub": "iam-role-sentinelops-agent",
                "role": "incident_commander",
                "tenant_id": "tenant-enterprise-alpha",
            }

        return False, "Unsupported authorization scheme", {}

    async def list_unified_tools(self) -> list[ToolDefinition]:
        """Expose aggregated tool catalog across all attached MCP targets."""
        catalog: list[ToolDefinition] = []
        for srv in self._targets.values():
            for tool_def in srv._tools.values():
                catalog.append(tool_def)
        return catalog

    async def route_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        auth_header: str | None = None,
        tenant_id: str = "default-tenant",
        environment: str = "production",
        trace_id: str | None = None,
    ) -> MCPResponse:
        """
        Execute tool call through Gateway:
        1. Inbound perimeter authorization check
        2. Outbound target mapping (injecting validated ActorContext)
        3. Dispatch to attached target MCP server
        """
        # 1. Inbound Auth
        is_authed, auth_msg, claims = self.verify_inbound_authorization(auth_header)
        if not is_authed:
            return MCPResponse.fail(
                req_id=uuid4().hex[:8],
                code=MCPErrorCode.UNAUTHORIZED,
                message=f"AgentCore Gateway inbound authorization failed: {auth_msg}",
            )

        # 2. Find target
        if tool_name not in self._tool_to_target:
            return MCPResponse.fail(
                req_id=uuid4().hex[:8],
                code=MCPErrorCode.TOOL_NOT_DISCOVERED,
                message=f"Tool '{tool_name}' not found in AgentCore Gateway catalog.",
            )

        target_name = self._tool_to_target[tool_name]
        target_server = self._targets[target_name]

        # 3. Outbound Context Mapping
        metadata = ProtocolMetadata(
            client_id=f"agentcore-{self.gateway_id}",
            tenant_id=claims.get("tenant_id", tenant_id),
            environment=environment,
            actor_id=claims.get("sub", "system"),
            actor_role=claims.get("role", "operator"),
            trace_id=trace_id,
        )

        req = MCPRequest(
            method="tools/call",
            params={"name": tool_name, "arguments": arguments},
            metadata=metadata,
        )

        # 4. Dispatch to target server
        return await target_server.handle_request(req)
