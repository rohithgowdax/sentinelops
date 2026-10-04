"""
MCP Generalization Contract Tests for SentinelOps Slice 5.

Proves:
1. Agent -> MCP -> Canonical Capability abstraction can interchange backend provider implementations
   without modifying agent schemas, tool contracts, or client code.
2. Provider A (MockServiceDeploymentProvider) vs Provider B (MockContainerProvider)
   exhibit exact behavioral equivalence under the same MCP Remediation tool definition.
3. Static AST analysis proves zero provider-specific if/elif branching inside the MCP server layer.
"""
from __future__ import annotations

import ast
import inspect
import pytest

from sentinelops.domain.models.action import ActionStatus
from sentinelops.integrations.actions.mock_container import MockContainerProvider
from sentinelops.integrations.actions.mock_deployment import MockServiceDeploymentProvider
from sentinelops.mcp.client import MCPClient
from sentinelops.mcp.servers import change, knowledge, remediation, telemetry
from sentinelops.mcp.servers.remediation import create_remediation_mcp_server


class TestMCPGeneralizationContract:
    def test_zero_provider_branching_in_mcp_servers_ast(self) -> None:
        """
        Verify that MCP server implementations contain zero branching on concrete vendor strings.
        """
        prohibited = {
            "kubernetes",
            "k8s",
            "ecs",
            "aws",
            "docker",
            "mock_service_deployment_provider",
            "mock_container_provider",
        }

        for mod in [telemetry, knowledge, change, remediation]:
            source = inspect.getsource(mod)
            tree = ast.parse(source)

            for node in ast.walk(tree):
                if isinstance(node, ast.Compare):
                    for comparator in node.comparators:
                        if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                            val = comparator.value.lower()
                            assert val not in prohibited, (
                                f"Forbidden vendor branch '{val}' detected in {mod.__name__}:{node.lineno}"
                            )

    @pytest.mark.asyncio
    async def test_canonical_mcp_action_equivalence_across_providers(self) -> None:
        """
        Prove that identical MCP tool call payloads execute identically across
        MockServiceDeploymentProvider (Provider A) and MockContainerProvider (Provider B).
        """
        provider_a = MockServiceDeploymentProvider()
        provider_b = MockContainerProvider()

        server_a = create_remediation_mcp_server(action_provider=provider_a, server_name="mcp-remediation-a")
        server_b = create_remediation_mcp_server(action_provider=provider_b, server_name="mcp-remediation-b")

        client_a = MCPClient(server_a)
        client_b = MCPClient(server_b)

        # Identical arguments passed to both
        payload = {
            "incident_id": "INC-GEN-01",
            "action_type": "restart_service",
            "target_service": "payments-service",
            "parameters": {},
            "rationale": "Automated restart to restore degraded state",
        }

        # Execute on Provider A via MCP
        resp_a = await client_a.call_tool(
            "execute_action",
            payload,
            environment="staging",
            actor_id="sre-actor",
            actor_role="sre",
        )

        # Execute on Provider B via MCP
        resp_b = await client_b.call_tool(
            "execute_action",
            payload,
            environment="staging",
            actor_id="sre-actor",
            actor_role="sre",
        )

        assert resp_a.error is None
        assert resp_b.error is None
        assert resp_a.result["status"] == "succeeded"
        assert resp_b.result["status"] == "succeeded"
        assert resp_a.result["remediation_status"] == "resolved"
        assert resp_b.result["remediation_status"] == "resolved"
        assert resp_a.result["provider"] == provider_a.provider_name
        assert resp_b.result["provider"] == provider_b.provider_name
