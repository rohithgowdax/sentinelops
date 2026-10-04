"""
Base Model Context Protocol (MCP) Server for SentinelOps (Revision 2026-07-28).

Provides:
- Tool registration and JSON Schema validation
- Resource registration and URI routing
- Explicit discovery (`server/discover`, `tools/list`, `resources/list`) with cache hints
- Context preservation (tenant_id, actor, environment, trace_id)
- Structured error mapping (never leaking raw exceptions or secrets)
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable
from pydantic import ValidationError

from sentinelops.mcp.protocol import (
    CacheHint,
    DiscoveryResult,
    MCPError,
    MCPErrorCode,
    MCPRequest,
    MCPResponse,
    MCP_PROTOCOL_VERSION,
    ProtocolMetadata,
    ResourceContent,
    ResourceDefinition,
    ServerCapabilities,
    ToolDefinition,
)

logger = logging.getLogger(__name__)

ToolHandler = Callable[[dict[str, Any], ProtocolMetadata], Awaitable[dict[str, Any]]]
ResourceHandler = Callable[[str, ProtocolMetadata], Awaitable[ResourceContent]]


class MCPServer:
    """
    Stateless Model Context Protocol (MCP) Server implementing revision 2026-07-28.
    """

    def __init__(
        self,
        name: str,
        version: str = "1.0.0",
        description: str | None = None,
        cache_ttl_seconds: int = 300,
    ) -> None:
        self.name = name
        self.version = version
        self.description = description or f"SentinelOps {name} MCP Server"
        self.cache_ttl_seconds = cache_ttl_seconds

        self._tools: dict[str, ToolDefinition] = {}
        self._tool_handlers: dict[str, ToolHandler] = {}
        self._resources: dict[str, ResourceDefinition] = {}
        self._resource_handlers: dict[str, ResourceHandler] = {}

    def register_tool(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
    ) -> None:
        """Register an MCP tool with schema and async handler."""
        self._tools[definition.name] = definition
        self._tool_handlers[definition.name] = handler
        logger.debug("Registered MCP tool '%s' on server '%s'", definition.name, self.name)

    def register_resource(
        self,
        definition: ResourceDefinition,
        handler: ResourceHandler,
    ) -> None:
        """Register an MCP read-only operational resource with URI pattern."""
        self._resources[definition.uri] = definition
        self._resource_handlers[definition.uri] = handler
        logger.debug("Registered MCP resource '%s' on server '%s'", definition.uri, self.name)

    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        """
        Dispatches incoming JSON-RPC request to appropriate handler.
        Stateless: parses per-request ProtocolMetadata.
        """
        method = request.method
        req_id = request.id
        metadata = request.metadata

        try:
            if method == "server/discover":
                return self._handle_discover(req_id, metadata)
            elif method == "tools/list":
                return self._handle_tools_list(req_id, metadata)
            elif method == "tools/call":
                return await self._handle_tools_call(req_id, request.params, metadata)
            elif method == "resources/list":
                return self._handle_resources_list(req_id, metadata)
            elif method == "resources/read":
                return await self._handle_resources_read(req_id, request.params, metadata)
            else:
                return MCPResponse.fail(
                    req_id,
                    MCPErrorCode.METHOD_NOT_FOUND,
                    f"Method '{method}' is not supported by MCP server '{self.name}'.",
                    metadata=metadata,
                )
        except Exception as exc:
            logger.exception("Unexpected error processing MCP request %s: %s", req_id, exc)
            return MCPResponse.fail(
                req_id,
                MCPErrorCode.INTERNAL_ERROR,
                "Internal server error occurred while executing MCP request.",
                metadata=metadata,
            )

    def _handle_discover(self, req_id: str | int, metadata: ProtocolMetadata) -> MCPResponse:
        discovery = DiscoveryResult(
            server_name=self.name,
            server_version=self.version,
            protocol_version=MCP_PROTOCOL_VERSION,
            capabilities=ServerCapabilities(tools=True, resources=True, elicitation=True, stateless=True),
            cache_hint=CacheHint(max_age_seconds=self.cache_ttl_seconds, scope="public"),
            tools_count=len(self._tools),
            resources_count=len(self._resources),
        )
        return MCPResponse.success(req_id, discovery.model_dump(), metadata)

    def _handle_tools_list(self, req_id: str | int, metadata: ProtocolMetadata) -> MCPResponse:
        tools_list = [t.model_dump() for t in self._tools.values()]
        return MCPResponse.success(req_id, {"tools": tools_list}, metadata)

    async def _handle_tools_call(
        self,
        req_id: str | int,
        params: dict[str, Any],
        metadata: ProtocolMetadata,
    ) -> MCPResponse:
        tool_name = params.get("name")
        if not tool_name:
            return MCPResponse.fail(
                req_id,
                MCPErrorCode.INVALID_PARAMS,
                "Missing 'name' parameter for tools/call.",
                metadata=metadata,
            )

        if tool_name not in self._tools:
            return MCPResponse.fail(
                req_id,
                MCPErrorCode.TOOL_NOT_DISCOVERED,
                f"Tool '{tool_name}' is not registered on MCP server '{self.name}'.",
                metadata=metadata,
            )

        tool_def = self._tools[tool_name]
        arguments = params.get("arguments", {})

        # Validate arguments against inputSchema
        validation_error = self._validate_arguments(tool_def.inputSchema, arguments)
        if validation_error:
            return MCPResponse.fail(
                req_id,
                MCPErrorCode.INVALID_PARAMS,
                f"Schema validation failed for tool '{tool_name}': {validation_error}",
                metadata=metadata,
            )

        # Enforce authorization if tool requires it
        if tool_def.requires_authorization:
            if not metadata.actor_role:
                return MCPResponse.fail(
                    req_id,
                    MCPErrorCode.UNAUTHORIZED,
                    f"Tool '{tool_name}' requires an authenticated actor context, but none was provided.",
                    metadata=metadata,
                )

        handler = self._tool_handlers[tool_name]
        try:
            result = await handler(arguments, metadata)
            # Check if handler explicitly returned an MCPError structure
            if isinstance(result, dict) and "mcp_error" in result:
                err_info = result["mcp_error"]
                return MCPResponse.fail(
                    req_id,
                    err_info.get("code", MCPErrorCode.INTERNAL_ERROR),
                    err_info.get("message", "Tool execution rejected."),
                    data=err_info.get("data"),
                    metadata=metadata,
                )
            return MCPResponse.success(req_id, result, metadata)
        except Exception as exc:
            logger.exception("Error during execution of tool '%s': %s", tool_name, exc)
            return MCPResponse.fail(
                req_id,
                MCPErrorCode.INTERNAL_ERROR,
                f"Tool execution failed for '{tool_name}'.",
                metadata=metadata,
            )

    def _handle_resources_list(self, req_id: str | int, metadata: ProtocolMetadata) -> MCPResponse:
        resources_list = [r.model_dump() for r in self._resources.values()]
        return MCPResponse.success(req_id, {"resources": resources_list}, metadata)

    async def _handle_resources_read(
        self,
        req_id: str | int,
        params: dict[str, Any],
        metadata: ProtocolMetadata,
    ) -> MCPResponse:
        uri = params.get("uri")
        if not uri:
            return MCPResponse.fail(
                req_id,
                MCPErrorCode.INVALID_PARAMS,
                "Missing 'uri' parameter for resources/read.",
                metadata=metadata,
            )

        # Match exact URI or prefix matching
        matched_handler: ResourceHandler | None = None
        for reg_uri, handler in self._resource_handlers.items():
            if reg_uri == uri or (reg_uri.endswith("}") and uri.startswith(reg_uri.split("{")[0])):
                matched_handler = handler
                break

        if not matched_handler:
            return MCPResponse.fail(
                req_id,
                MCPErrorCode.RESOURCE_NOT_FOUND,
                f"Resource URI '{uri}' not found on server '{self.name}'.",
                metadata=metadata,
            )

        try:
            content = await matched_handler(uri, metadata)
            return MCPResponse.success(req_id, content.model_dump(), metadata)
        except Exception as exc:
            logger.exception("Error reading resource '%s': %s", uri, exc)
            return MCPResponse.fail(
                req_id,
                MCPErrorCode.INTERNAL_ERROR,
                f"Failed to read resource '{uri}'.",
                metadata=metadata,
            )

    def _validate_arguments(self, schema: dict[str, Any], arguments: dict[str, Any]) -> str | None:
        """Lightweight JSON Schema validation for tool arguments."""
        required = schema.get("required", [])
        for field in required:
            if field not in arguments:
                return f"Missing required parameter '{field}'"

        properties = schema.get("properties", {})
        for key, val in arguments.items():
            if key in properties:
                expected_type = properties[key].get("type")
                if expected_type == "string" and not isinstance(val, str):
                    return f"Parameter '{key}' must be a string, got {type(val).__name__}"
                elif expected_type == "integer" and not isinstance(val, int):
                    return f"Parameter '{key}' must be an integer, got {type(val).__name__}"
                elif expected_type == "number" and not isinstance(val, (int, float)):
                    return f"Parameter '{key}' must be a number, got {type(val).__name__}"
                elif expected_type == "boolean" and not isinstance(val, bool):
                    return f"Parameter '{key}' must be a boolean, got {type(val).__name__}"
                elif expected_type == "object" and not isinstance(val, dict):
                    return f"Parameter '{key}' must be an object, got {type(val).__name__}"
                elif expected_type == "array" and not isinstance(val, list):
                    return f"Parameter '{key}' must be an array, got {type(val).__name__}"
        return None
