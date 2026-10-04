"""
Unit Tests for Telemetry, Knowledge, Change, and Remediation MCP Servers.
"""
from __future__ import annotations

import pytest

from sentinelops.approval.service import ApprovalService
from sentinelops.audit.service import AuditService
from sentinelops.domain.models.policy import ActorRole, PolicyDecisionType
from sentinelops.integrations.actions.mock_deployment import MockServiceDeploymentProvider
from sentinelops.mcp.client import MCPClient
from sentinelops.mcp.protocol import MCPErrorCode
from sentinelops.mcp.servers import (
    create_change_mcp_server,
    create_knowledge_mcp_server,
    create_remediation_mcp_server,
    create_telemetry_mcp_server,
)
from sentinelops.policy.engine import PolicyEngine


class TestFocusedMCPServers:
    @pytest.mark.asyncio
    async def test_telemetry_mcp_server_tools_and_resources(self) -> None:
        server = create_telemetry_mcp_server()
        client = MCPClient(server)

        # 1. query_metrics
        resp_m = await client.call_tool("query_metrics", {"service": "payments-service", "metric": "http.error_rate"})
        assert resp_m.error is None
        assert resp_m.result["service"] == "payments-service"
        assert "mean" in resp_m.result or "data" in resp_m.result

        # 2. query_logs
        resp_l = await client.call_tool("query_logs", {"service": "payments-service", "limit": 2})
        assert resp_l.error is None
        assert len(resp_l.result["logs"]) <= 2

        # 3. get_service_health
        resp_h = await client.call_tool("get_service_health", {"service": "payments-service"})
        assert resp_h.error is None
        assert "status" in resp_h.result

        # 4. get_dependencies
        resp_d = await client.call_tool("get_dependencies", {"service": "payments-service"})
        assert resp_d.error is None
        assert "upstream" in resp_d.result
        assert "downstream" in resp_d.result

        # Resource: sentinel://services/payments-service
        resp_r = await client.read_resource("sentinel://services/payments-service")
        assert resp_r.error is None
        assert "payments-sre-team" in resp_r.result["text"]

    @pytest.mark.asyncio
    async def test_knowledge_mcp_server_tools_and_resources(self) -> None:
        server = create_knowledge_mcp_server()
        client = MCPClient(server)

        # 1. search_knowledge
        resp_s = await client.call_tool("search_knowledge", {"query": "how to restart pod", "limit": 2})
        assert resp_s.error is None
        assert resp_s.result["total_results"] >= 1

        # 2. get_document
        resp_d = await client.call_tool("get_document", {"document_id": "RB-PAY-001"})
        assert resp_d.error is None
        assert resp_d.result["document_id"] == "RB-PAY-001"

        # 3. get_evidence
        resp_e = await client.call_tool("get_evidence", {"chunk_id": "CHK-01"})
        assert resp_e.error is None
        assert resp_e.result["valid"] is True

        # Resource
        resp_r = await client.read_resource("sentinel://knowledge/RB-PAY-001")
        assert resp_r.error is None
        assert "RB-PAY-001" in resp_r.result["text"]

    @pytest.mark.asyncio
    async def test_change_mcp_server_tools_and_resources(self) -> None:
        server = create_change_mcp_server()
        client = MCPClient(server)

        # 1. list_recent_changes
        resp_c = await client.call_tool("list_recent_changes", {"service": "payments-service", "limit": 3})
        assert resp_c.error is None
        assert len(resp_c.result["changes"]) <= 3

        # 2. get_deployment
        resp_d = await client.call_tool("get_deployment", {"service": "payments-service"})
        assert resp_d.error is None
        assert resp_d.result["active_version"] == "1.8.3"

        # 3. get_resource_version
        resp_v = await client.call_tool("get_resource_version", {"service": "payments-service"})
        assert resp_v.error is None
        assert resp_v.result["current_version"] == "1.8.3"

        # Resource
        resp_r = await client.read_resource("sentinel://deployments/payments-service")
        assert resp_r.error is None
        assert "1.8.3" in resp_r.result["text"]

    @pytest.mark.asyncio
    async def test_remediation_mcp_server_propose_and_execute_flow(self) -> None:
        provider = MockServiceDeploymentProvider()
        policy = PolicyEngine()
        approvals = ApprovalService()
        audits = AuditService()

        server = create_remediation_mcp_server(
            action_provider=provider,
            policy_engine=policy,
            approval_service=approvals,
            audit_service=audits,
        )
        client = MCPClient(server)

        # 1. Propose action on staging -> ALLOW
        resp_prop_stg = await client.call_tool(
            "propose_action",
            {
                "incident_id": "INC-MCP-01",
                "action_type": "restart_service",
                "target_service": "payments-service",
                "parameters": {},
                "rationale": "Clear transient thread lock",
            },
            environment="staging",
        )
        assert resp_prop_stg.error is None
        assert resp_prop_stg.result["policy_decision"] == PolicyDecisionType.ALLOW.value
        assert resp_prop_stg.result["requires_approval"] is False

        # 2. Execute on staging -> Executes cleanly
        resp_exec_stg = await client.call_tool(
            "execute_action",
            {
                "incident_id": "INC-MCP-01",
                "action_type": "restart_service",
                "target_service": "payments-service",
                "parameters": {},
                "rationale": "Clear transient thread lock",
            },
            environment="staging",
            actor_id="sre-alice",
            actor_role="sre",
        )
        assert resp_exec_stg.error is None
        assert resp_exec_stg.result["status"] == "succeeded"
        assert resp_exec_stg.result["remediation_status"] == "resolved"
        assert len(provider._executed_actions) == 1
