"""
Unit Tests for MCPServer and MCPClient Dispatch and Caching.
"""
from __future__ import annotations

import pytest

from sentinelops.mcp.client import MCPClient
from sentinelops.mcp.protocol import (
    MCPErrorCode,
    MCPRequest,
    ProtocolMetadata,
    ResourceContent,
    ResourceDefinition,
    ToolDefinition,
)
from sentinelops.mcp.server import MCPServer


class TestServerAndClient:
    @pytest.fixture
    def sample_server(self) -> MCPServer:
        server = MCPServer(name="sample-server", version="1.0.0", cache_ttl_seconds=120)

        tool_echo = ToolDefinition(
            name="echo_tool",
            description="Echo back input parameters",
            inputSchema={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        )

        async def handle_echo(args: dict, meta: ProtocolMetadata) -> dict:
            return {"echo": args["message"], "client": meta.client_id}

        server.register_tool(tool_echo, handle_echo)

        res_info = ResourceDefinition(
            uri="sentinel://info/{topic}",
            name="Topic Info",
            description="Information on a given topic",
        )

        async def handle_info(uri: str, meta: ProtocolMetadata) -> ResourceContent:
            topic = uri.split("/")[-1]
            return ResourceContent(uri=uri, text=f"Information about {topic}")

        server.register_resource(res_info, handle_info)
        return server

    @pytest.mark.asyncio
    async def test_server_discovery(self, sample_server: MCPServer) -> None:
        client = MCPClient(sample_server)
        discovery = await client.discover()
        assert discovery.server_name == "sample-server"
        assert discovery.protocol_version == "2026-07-28"
        assert discovery.tools_count == 1
        assert discovery.resources_count == 1
        assert discovery.cache_hint.max_age_seconds == 120

    @pytest.mark.asyncio
    async def test_tools_list_and_call(self, sample_server: MCPServer) -> None:
        client = MCPClient(sample_server, client_id="test-client-99")
        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "echo_tool"

        resp = await client.call_tool("echo_tool", {"message": "hello sentinelops"})
        assert resp.error is None
        assert resp.result["echo"] == "hello sentinelops"
        assert resp.result["client"] == "test-client-99"

    @pytest.mark.asyncio
    async def test_schema_validation_rejects_missing_required(self, sample_server: MCPServer) -> None:
        client = MCPClient(sample_server)
        resp = await client.call_tool("echo_tool", {})  # Missing 'message'
        assert resp.error is not None
        assert resp.error.code == MCPErrorCode.INVALID_PARAMS
        assert "Missing required parameter" in resp.error.message

    @pytest.mark.asyncio
    async def test_schema_validation_rejects_wrong_type(self, sample_server: MCPServer) -> None:
        client = MCPClient(sample_server)
        resp = await client.call_tool("echo_tool", {"message": 12345})  # Expecting string
        assert resp.error is not None
        assert resp.error.code == MCPErrorCode.INVALID_PARAMS
        assert "must be a string" in resp.error.message

    @pytest.mark.asyncio
    async def test_resource_reading(self, sample_server: MCPServer) -> None:
        client = MCPClient(sample_server)
        resources = await client.list_resources()
        assert len(resources) == 1
        assert resources[0].uri == "sentinel://info/{topic}"

        resp = await client.read_resource("sentinel://info/architecture")
        assert resp.error is None
        assert "Information about architecture" in resp.result["text"]

    @pytest.mark.asyncio
    async def test_unknown_method_error(self, sample_server: MCPServer) -> None:
        req = MCPRequest(method="non_existent/method")
        resp = await sample_server.handle_request(req)
        assert resp.error is not None
        assert resp.error.code == MCPErrorCode.METHOD_NOT_FOUND
