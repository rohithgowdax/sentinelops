"""
Model Context Protocol (MCP) Module for SentinelOps (Revision 2026-07-28).
"""
from sentinelops.mcp.client import MCPClient
from sentinelops.mcp.protocol import (
    DiscoveryResult,
    MCPError,
    MCPErrorCode,
    MCPRequest,
    MCPResponse,
    MCP_PROTOCOL_VERSION,
    ProtocolMetadata,
    ResourceContent,
    ResourceDefinition,
    ToolDefinition,
)
from sentinelops.mcp.server import MCPServer

__all__ = [
    "MCPClient",
    "MCPServer",
    "MCP_PROTOCOL_VERSION",
    "MCPErrorCode",
    "MCPError",
    "MCPRequest",
    "MCPResponse",
    "ProtocolMetadata",
    "ToolDefinition",
    "ResourceDefinition",
    "ResourceContent",
    "DiscoveryResult",
]
