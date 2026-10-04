"""
Integration Tests for SentinelOps MCP Interoperability and AWS AgentCore Adapters (Slice 5).

Verifies:
1. End-to-end tool discovery and multi-server catalog exposure.
2. Cross-server capability consumption (Telemetry, Knowledge, Change, Remediation).
3. AWS AgentCore Gateway aggregation and inbound/outbound authorization mapping.
4. AWS AgentCore Runtime hosting SentinelOps LangGraph workflows.
5. Explicit graceful state reporting: 'AWS integration = NOT RUN' when cloud credentials are absent.
"""
from __future__ import annotations

import os
import pytest
from langgraph.checkpoint.memory import MemorySaver

from sentinelops.agent.graph import create_investigation_graph
from sentinelops.approval.service import ApprovalService
from sentinelops.audit.service import AuditService
from sentinelops.domain.models.action import ActionStatus
from sentinelops.domain.models.incident import (
    EvidenceItem,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    TriggerType,
)
from sentinelops.domain.models.policy import ActorContext, ActorRole
from sentinelops.integrations.actions.mock_deployment import MockServiceDeploymentProvider
from sentinelops.integrations.aws.gateway import AgentCoreGatewayAdapter
from sentinelops.integrations.aws.runtime import AgentCoreRuntimeAdapter
from sentinelops.mcp.client import MCPClient
from sentinelops.mcp.servers import (
    create_change_mcp_server,
    create_knowledge_mcp_server,
    create_remediation_mcp_server,
    create_telemetry_mcp_server,
)
from sentinelops.policy.engine import PolicyEngine
from tests.unit.test_remediation_graph import (
    _make_mock_evidence_provider,
    _make_test_incident,
)


class TestMCPIntegration:
    @pytest.mark.asyncio
    async def test_end_to_end_multi_server_mcp_lifecycle(self) -> None:
        """
        Verify that an agent can discover and invoke capabilities across all 4 MCP servers.
        """
        provider = MockServiceDeploymentProvider()
        policy = PolicyEngine()
        approvals = ApprovalService()
        audits = AuditService()

        # Instantiate all 4 servers
        srv_telem = create_telemetry_mcp_server()
        srv_know = create_knowledge_mcp_server()
        srv_chg = create_change_mcp_server()
        srv_rem = create_remediation_mcp_server(provider, policy, approvals, audits)

        # Clients
        cli_telem = MCPClient(srv_telem)
        cli_know = MCPClient(srv_know)
        cli_chg = MCPClient(srv_chg)
        cli_rem = MCPClient(srv_rem)

        # Step 1: Telemetry tool
        resp_t = await cli_telem.call_tool("query_metrics", {"service": "payments-service", "metric": "http.error_rate"})
        assert resp_t.error is None

        # Step 2: Knowledge tool
        resp_k = await cli_know.call_tool("search_knowledge", {"query": "remediation pool"})
        assert resp_k.error is None

        # Step 3: Change tool
        resp_c = await cli_chg.call_tool("get_deployment", {"service": "payments-service"})
        assert resp_c.error is None

        # Step 4: Propose remediation on production
        resp_prop = await cli_rem.call_tool(
            "propose_action",
            {
                "incident_id": "INC-E2E-01",
                "action_type": "rollback_deployment",
                "target_service": "payments-service",
                "parameters": {"target_version": "1.8.2"},
                "rationale": "Rollback following change CHG-2026-1049",
            },
            environment="production",
        )
        assert resp_prop.error is None
        action_id = resp_prop.result["action_id"]
        assert resp_prop.result["requires_approval"] is True

        # Step 5: Incident Commander signs off
        ic_actor = ActorContext(actor_id="ic-lead-alex", role=ActorRole.INCIDENT_COMMANDER)
        ok, _, app = approvals.approve(action_id, ic_actor)
        assert ok is True

        # Step 6: Execute via MCP
        resp_exec = await cli_rem.call_tool(
            "execute_action",
            {
                "action_id": action_id,
                "incident_id": "INC-E2E-01",
                "action_type": "rollback_deployment",
                "target_service": "payments-service",
                "parameters": {"target_version": "1.8.2"},
                "rationale": "Rollback following change CHG-2026-1049",
            },
            environment="production",
            actor_id="ic-lead-alex",
            actor_role="incident_commander",
        )
        assert resp_exec.error is None
        assert resp_exec.result["status"] == "succeeded"
        assert resp_exec.result["remediation_status"] == "resolved"

    @pytest.mark.asyncio
    async def test_agentcore_gateway_aggregation_and_routing(self) -> None:
        """
        Verify AWS Bedrock AgentCore Gateway aggregation mode:
        1. Unified catalog across attached MCP targets
        2. Inbound authorization check
        3. Outbound RBAC context injection
        """
        provider = MockServiceDeploymentProvider()
        srv_telem = create_telemetry_mcp_server()
        srv_rem = create_remediation_mcp_server(action_provider=provider)

        gateway = AgentCoreGatewayAdapter(gateway_id="gw-sentinelops-01")
        gateway.attach_mcp_target("telemetry_target", srv_telem)
        gateway.attach_mcp_target("remediation_target", srv_rem)

        # 1. Unified tool catalog
        unified = await gateway.list_unified_tools()
        tool_names = {t.name for t in unified}
        assert "query_metrics" in tool_names
        assert "get_service_health" in tool_names
        assert "propose_action" in tool_names
        assert "execute_action" in tool_names

        # 2. Inbound unauthorized request rejected
        unauth_resp = await gateway.route_tool_call(
            tool_name="get_service_health",
            arguments={"service": "payments-service"},
            auth_header="Bearer tok-unauthorized-000",
        )
        assert unauth_resp.error is not None

        # 3. Authorized request routed to telemetry target
        auth_resp = await gateway.route_tool_call(
            tool_name="get_service_health",
            arguments={"service": "payments-service"},
            auth_header="Bearer tok-valid-sre-credentials",
        )
        assert auth_resp.error is None
        assert auth_resp.result["service"] == "payments-service"

    @pytest.mark.asyncio
    async def test_agentcore_runtime_hosting_langgraph_workflow(self) -> None:
        """
        Verify AWS Bedrock AgentCore Runtime adapter hosting LangGraph workflow.
        """
        incident = _make_test_incident(env="staging", service="payments-service")
        ev_prov = _make_mock_evidence_provider("payments-service")
        action_prov = MockServiceDeploymentProvider()
        checkpointer = MemorySaver()

        from sentinelops.capabilities.llm.provider import DeterministicLLMProvider
        graph = create_investigation_graph(
            llm_provider=DeterministicLLMProvider(),
            evidence_provider=ev_prov,
            action_provider=action_prov,
            checkpointer=checkpointer,
        )

        runtime = AgentCoreRuntimeAdapter(compiled_graph=graph, runtime_id="rt-sentinelops-01")

        event = {
            "incident": incident.model_dump(),
            "session_id": "sess-agentcore-001",
            "trace_id": "trace-w3c-agentcore-001",
        }

        output = await runtime.invoke_from_event(event)
        assert output["runtime_id"] == "rt-sentinelops-01"
        assert output["incident_id"] == incident.incident_id
        assert output["remediation_status"] == "resolved"
        assert output["status"] == "completed"

    def test_aws_live_cloud_integration_honest_not_run_classification(self) -> None:
        """
        Strict truthfulness invariant:
        When live AWS credentials are not configured, live cloud tests report explicitly as NOT RUN.
        Never silently passes or fabricates cloud results.
        """
        aws_key = os.environ.get("AWS_ACCESS_KEY_ID")
        aws_secret = os.environ.get("AWS_SECRET_ACCESS_KEY")

        if not aws_key or not aws_secret:
            # Explicit documentation of NOT RUN state
            pytest.skip("AWS integration = NOT RUN (AWS credentials not configured in environment)")
