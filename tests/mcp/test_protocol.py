"""
Unit Tests for MCP 2026-07-28 Protocol Models and Serialization.
"""
from __future__ import annotations

import json
import pytest

from sentinelops.mcp.protocol import (
    CacheHint,
    DiscoveryResult,
    ElicitationRequest,
    ElicitationStatus,
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


class TestMCPProtocol:
    def test_protocol_version_pinned_to_2026_07_28(self) -> None:
        assert MCP_PROTOCOL_VERSION == "2026-07-28"

    def test_protocol_metadata_defaults(self) -> None:
        meta = ProtocolMetadata()
        assert meta.protocol_version == "2026-07-28"
        assert meta.request_id.startswith("req-")
        assert meta.tenant_id == "default-tenant"
        assert meta.environment == "production"

    def test_jsonrpc_request_and_response_roundtrip(self) -> None:
        req = MCPRequest(
            method="tools/call",
            params={"name": "query_metrics", "arguments": {"service": "payments"}},
            metadata=ProtocolMetadata(actor_id="sre-01", actor_role="sre"),
        )
        assert req.jsonrpc == "2.0"
        dumped = req.model_dump_json()
        parsed = json.loads(dumped)
        assert parsed["method"] == "tools/call"
        assert parsed["metadata"]["actor_role"] == "sre"

        resp = MCPResponse.success(req_id=req.id, result={"status": "ok"}, metadata=req.metadata)
        assert resp.jsonrpc == "2.0"
        assert resp.error is None
        assert resp.result["status"] == "ok"

    def test_mcp_error_response_construction(self) -> None:
        resp = MCPResponse.fail(
            req_id="test-123",
            code=MCPErrorCode.POLICY_DENIED,
            message="Action denied by policy rule",
            data={"reason": "Prohibited destructive operation"},
        )
        assert resp.error is not None
        assert resp.error.code == -32001
        assert resp.error.message == "Action denied by policy rule"
        assert resp.error.data["reason"] == "Prohibited destructive operation"

    def test_elicitation_request_model(self) -> None:
        elc = ElicitationRequest(
            action_id="ACT-001",
            incident_id="INC-001",
            message="Production rollback requires human approval",
            required_role="incident_commander",
            parameters={"target_version": "1.8.2"},
        )
        assert elc.status == ElicitationStatus.PENDING
        assert elc.required_role == "incident_commander"

    def test_discovery_result_model(self) -> None:
        disc = DiscoveryResult(
            server_name="test-server",
            server_version="1.0.0",
            protocol_version="2026-07-28",
            capabilities=ServerCapabilities(tools=True, resources=True, elicitation=True, stateless=True),
            cache_hint=CacheHint(max_age_seconds=600),
            tools_count=4,
            resources_count=2,
        )
        assert disc.protocol_version == "2026-07-28"
        assert disc.capabilities.stateless is True
        assert disc.cache_hint.max_age_seconds == 600
