"""
Model Context Protocol (MCP) Protocol Specification — Revision 2026-07-28.

Key Characteristics of 2026-07-28 Revision:
- Stateless at the transport and protocol layer: requests carry full protocol metadata.
  No required legacy stateful handshake (`initialize`) or session-id header (`Mcp-Session-Id`).
- Supports multi-round-trip request handling and elicitation for human-in-the-loop interactions.
- Explicit `server/discover` discovery endpoint and cache hints for tool/resource catalogs.
- Typed tool and resource definitions with strict JSON Schema specifications.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import IntEnum, Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

# Authoritative MCP Protocol Version Pinned
MCP_PROTOCOL_VERSION = "2026-07-28"


class MCPErrorCode(IntEnum):
    """MCP Standard and Domain-Specific JSON-RPC Error Codes."""

    # Standard JSON-RPC 2.0 Error Codes
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # SentinelOps MCP Domain Error Codes
    POLICY_DENIED = -32001
    APPROVAL_REQUIRED = -32002
    RESOURCE_NOT_FOUND = -32003
    UNAUTHORIZED = -32004
    VERIFICATION_FAILED = -32005
    ARGUMENT_TAMPERING = -32006
    TOOL_NOT_DISCOVERED = -32007
    PROVIDER_UNAVAILABLE = -32008
    TIMEOUT = -32009


class MCPError(BaseModel):
    """Structured MCP Error Model."""

    code: int = Field(..., description="Error code identifier")
    message: str = Field(..., description="Human-readable safe error summary (no stack traces or secrets)")
    data: dict[str, Any] | None = Field(default=None, description="Structured contextual error details")


class ProtocolMetadata(BaseModel):
    """
    Stateless request metadata defined in MCP 2026-07-28.
    Carries identity, trace context, tenant, and protocol version per-request.
    """

    protocol_version: str = Field(default=MCP_PROTOCOL_VERSION)
    request_id: str = Field(default_factory=lambda: f"req-{uuid4().hex[:12]}")
    client_id: str | None = Field(default=None, description="Calling client identity")
    tenant_id: str | None = Field(default="default-tenant", description="Organizational tenant scope")
    environment: str = Field(default="production", description="Target environment scope")
    actor_id: str | None = Field(default=None, description="Authenticated actor identity")
    actor_role: str | None = Field(default=None, description="Role: operator, sre, incident_commander, admin")
    trace_id: str | None = Field(default=None, description="W3C TraceContext trace ID")
    span_id: str | None = Field(default=None, description="W3C TraceContext span ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


class ToolDefinition(BaseModel):
    """Definition and JSON Schema for an MCP Tool."""

    name: str = Field(..., description="Unique tool name")
    description: str = Field(..., description="Clear explanation of tool utility and safety boundaries")
    inputSchema: dict[str, Any] = Field(..., description="JSON Schema for input parameters")
    outputSchema: dict[str, Any] | None = Field(default=None, description="Optional JSON Schema for tool return value")
    is_mutation: bool = Field(default=False, description="Whether this tool mutates infrastructure or is read-only")
    requires_authorization: bool = Field(default=False, description="Whether tool requires authenticated actor role")


class ResourceDefinition(BaseModel):
    """Definition for an MCP Read-Only Operational Resource."""

    uri: str = Field(..., description="Canonical URI template, e.g. 'sentinel://services/{service_id}'")
    name: str = Field(..., description="Human-readable resource name")
    description: str = Field(..., description="Resource description")
    mimeType: str = Field(default="application/json", description="Content MIME type")


class ResourceContent(BaseModel):
    """Content returned when reading an MCP Resource."""

    uri: str = Field(...)
    mimeType: str = Field(default="application/json")
    text: str | None = Field(default=None, description="Textual or JSON payload")
    blob: str | None = Field(default=None, description="Base64 encoded binary payload if applicable")


class CacheHint(BaseModel):
    """Caching hint for tool and resource discovery in 2026-07-28 specification."""

    max_age_seconds: int = Field(default=300)
    scope: str = Field(default="public", description="'public', 'private', or 'session'")


class ServerCapabilities(BaseModel):
    """Server capabilities returned during discovery."""

    tools: bool = Field(default=True)
    resources: bool = Field(default=True)
    elicitation: bool = Field(default=True, description="Multi-round-trip interaction support")
    stateless: bool = Field(default=True, description="2026-07-28 stateless protocol conformance")


class DiscoveryResult(BaseModel):
    """Payload returned by 'server/discover' endpoint."""

    server_name: str = Field(...)
    server_version: str = Field(...)
    protocol_version: str = Field(default=MCP_PROTOCOL_VERSION)
    capabilities: ServerCapabilities = Field(default_factory=ServerCapabilities)
    cache_hint: CacheHint = Field(default_factory=CacheHint)
    tools_count: int = Field(default=0)
    resources_count: int = Field(default=0)


class ElicitationStatus(str, Enum):
    """Status for multi-round-trip elicitation."""

    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ElicitationRequest(BaseModel):
    """
    Multi-round-trip elicitation request (2026-07-28 revision).
    Used when a tool execution requires human approval or additional clarification.
    """

    elicitation_id: str = Field(default_factory=lambda: f"elc-{uuid4().hex[:8]}")
    action_id: str = Field(...)
    incident_id: str = Field(...)
    message: str = Field(..., description="Explanation of required input or approval")
    required_role: str = Field(...)
    parameters: dict[str, Any] = Field(default_factory=dict)
    status: ElicitationStatus = Field(default=ElicitationStatus.PENDING)


class MCPRequest(BaseModel):
    """Standard JSON-RPC 2.0 Request with 2026-07-28 Protocol Metadata."""

    jsonrpc: str = Field(default="2.0")
    id: str | int = Field(default_factory=lambda: uuid4().hex[:8])
    method: str = Field(..., description="e.g. 'server/discover', 'tools/list', 'tools/call', 'resources/read'")
    params: dict[str, Any] = Field(default_factory=dict)
    metadata: ProtocolMetadata = Field(default_factory=ProtocolMetadata)


class MCPResponse(BaseModel):
    """Standard JSON-RPC 2.0 Response with 2026-07-28 Protocol Metadata."""

    jsonrpc: str = Field(default="2.0")
    id: str | int = Field(...)
    result: Any | None = Field(default=None)
    error: MCPError | None = Field(default=None)
    metadata: ProtocolMetadata = Field(default_factory=ProtocolMetadata)

    @classmethod
    def success(cls, req_id: str | int, result: Any, metadata: ProtocolMetadata | None = None) -> MCPResponse:
        return cls(id=req_id, result=result, metadata=metadata or ProtocolMetadata())

    @classmethod
    def fail(
        cls,
        req_id: str | int,
        code: int | MCPErrorCode,
        message: str,
        data: dict[str, Any] | None = None,
        metadata: ProtocolMetadata | None = None,
    ) -> MCPResponse:
        return cls(
            id=req_id,
            error=MCPError(code=int(code), message=message, data=data),
            metadata=metadata or ProtocolMetadata(),
        )
