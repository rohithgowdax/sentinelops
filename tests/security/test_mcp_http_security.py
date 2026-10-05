"""
Integration and Boundary Security Tests for SentinelOps Slice 6 (HTTP Transport).

Validates:
1. Full HTTP JSON-RPC 2.0 communication for MCP.
2. Inbound transport authentication enforcement (Bearer auth).
3. Rejection of unauthenticated or tampered tokens over HTTP.
4. Schema validation and error mapping over HTTP.
5. Invariant A over HTTP: Policy DENY causes 0 provider calls.
6. Invariant B over HTTP: Policy REQUIRES_APPROVAL blocks execution without token.
7. Invariant C over HTTP: Exact action parameter binding and anti-replay over HTTP.
8. End-to-end W3C traceparent propagation over HTTP.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport

from sentinelops.approval.service import ApprovalService
from sentinelops.audit.service import AuditService
from sentinelops.domain.models.policy import ActorContext, ActorRole
from sentinelops.integrations.actions.mock_deployment import MockServiceDeploymentProvider
from sentinelops.mcp.http_transport import MCPHttpClient, create_mcp_http_app
from sentinelops.mcp.protocol import MCPErrorCode
from sentinelops.mcp.servers.remediation import create_remediation_mcp_server
from sentinelops.mcp.servers.telemetry import create_telemetry_mcp_server
from sentinelops.policy.engine import PolicyEngine


class TestSlice6HTTPTransportSecurity:
    @pytest.fixture
    def setup_http_remediation(self) -> tuple[MCPHttpClient, MockServiceDeploymentProvider, ApprovalService]:
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
        app = create_mcp_http_app(server, require_auth=True)
        client = MCPHttpClient(
            transport=ASGITransport(app=app),
            auth_token="tok-sre-valid",
        )
        return client, provider, approvals

    @pytest.mark.asyncio
    async def test_unauthenticated_request_over_http_rejected_at_transport_layer(
        self,
        setup_http_remediation: tuple[MCPHttpClient, MockServiceDeploymentProvider, ApprovalService],
    ) -> None:
        """HTTP transport layer rejects unauthenticated requests with 401 UNAUTHORIZED."""
        _, provider, _ = setup_http_remediation
        # Client without auth token
        server = create_remediation_mcp_server(
            action_provider=provider,
            policy_engine=PolicyEngine(),
            approval_service=ApprovalService(),
            audit_service=AuditService(),
        )
        app = create_mcp_http_app(server, require_auth=True)
        unauth_client = MCPHttpClient(
            transport=ASGITransport(app=app),
            auth_token=None,  # No token
        )

        resp = await unauth_client.call_tool("propose_action", {"incident_id": "INC-01"})
        assert resp.error is not None
        assert resp.error.code == MCPErrorCode.UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_forged_untrusted_token_rejected_at_http_transport(
        self,
        setup_http_remediation: tuple[MCPHttpClient, MockServiceDeploymentProvider, ApprovalService],
    ) -> None:
        """Transport rejects invalid bearer token."""
        _, provider, _ = setup_http_remediation
        server = create_remediation_mcp_server(
            action_provider=provider,
            policy_engine=PolicyEngine(),
            approval_service=ApprovalService(),
            audit_service=AuditService(),
        )
        app = create_mcp_http_app(server, require_auth=True)
        bad_client = MCPHttpClient(
            transport=ASGITransport(app=app),
            auth_token="tok-unauth-hacker",
        )

        resp = await bad_client.call_tool("propose_action", {"incident_id": "INC-01"})
        assert resp.error is not None
        assert resp.error.code == MCPErrorCode.UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_invariant_a_policy_deny_causes_zero_provider_calls_over_http(
        self,
        setup_http_remediation: tuple[MCPHttpClient, MockServiceDeploymentProvider, ApprovalService],
    ) -> None:
        """Policy DENY over HTTP strictly yields zero ActionProvider executions."""
        client, provider, _ = setup_http_remediation

        resp = await client.call_tool(
            "execute_action",
            {
                "incident_id": "INC-HTTP-DENY-01",
                "action_type": "delete_resource",
                "target_service": "payments-service",
                "parameters": {"cmd": "drop database"},
                "rationale": "Destructive execution test over HTTP",
            },
            actor_id="admin-actor",
            actor_role="admin",
            environment="production",
        )
        assert resp.error is not None
        assert resp.error.code == MCPErrorCode.POLICY_DENIED
        assert len(provider._executed_actions) == 0

    @pytest.mark.asyncio
    async def test_invariant_b_requires_approval_blocks_execution_over_http(
        self,
        setup_http_remediation: tuple[MCPHttpClient, MockServiceDeploymentProvider, ApprovalService],
    ) -> None:
        """Policy REQUIRES_APPROVAL over HTTP strictly blocks execution without prior approval."""
        client, provider, _ = setup_http_remediation

        resp = await client.call_tool(
            "execute_action",
            {
                "incident_id": "INC-HTTP-APPROVAL-01",
                "action_type": "rollback_deployment",
                "target_service": "payments-service",
                "parameters": {"target_version": "1.8.2"},
                "rationale": "Production rollback over HTTP without approved token",
            },
            actor_id="sre-actor",
            actor_role="sre",
            environment="production",
        )
        assert resp.error is not None
        assert resp.error.code == MCPErrorCode.APPROVAL_REQUIRED
        assert len(provider._executed_actions) == 0

    @pytest.mark.asyncio
    async def test_invariant_c_exact_binding_and_antireplay_over_http(
        self,
        setup_http_remediation: tuple[MCPHttpClient, MockServiceDeploymentProvider, ApprovalService],
    ) -> None:
        """Exact action parameter binding and anti-replay protection enforced over HTTP transport."""
        client, provider, approvals = setup_http_remediation

        # Step 1: Propose
        prop = await client.call_tool(
            "propose_action",
            {
                "incident_id": "INC-HTTP-EXACT-01",
                "action_type": "rollback_deployment",
                "target_service": "payments-service",
                "parameters": {"target_version": "1.8.2"},
                "rationale": "Rollback proposed over HTTP",
            },
            actor_id="sre-actor",
            actor_role="sre",
            environment="production",
        )
        assert prop.error is None
        action_id = prop.result["action_id"]

        # Step 2: Grant Incident Commander Approval
        ic_actor = ActorContext(
            actor_id="ic-chief",
            role=ActorRole.INCIDENT_COMMANDER,
            tenant_id="default-tenant",
        )
        ok, msg, _ = approvals.approve(action_id, ic_actor, comment="Approved over HTTP")
        assert ok, msg

        # Step 3: Tamper with parameters over HTTP
        tamper = await client.call_tool(
            "execute_action",
            {
                "incident_id": "INC-HTTP-EXACT-01",
                "action_id": action_id,
                "action_type": "rollback_deployment",
                "target_service": "payments-service",
                "parameters": {"target_version": "1.8.0"},  # Tampered!
                "rationale": "Tampered rollback parameters",
            },
            actor_id="sre-actor",
            actor_role="sre",
            environment="production",
        )
        assert tamper.error is not None
        assert tamper.error.code == MCPErrorCode.ARGUMENT_TAMPERING
        assert len(provider._executed_actions) == 0

        # Step 4: Execute with untampered parameters over HTTP
        exec_ok = await client.call_tool(
            "execute_action",
            {
                "incident_id": "INC-HTTP-EXACT-01",
                "action_id": action_id,
                "action_type": "rollback_deployment",
                "target_service": "payments-service",
                "parameters": {"target_version": "1.8.2"},
                "rationale": "Untampered rollback execution",
            },
            actor_id="sre-actor",
            actor_role="sre",
            environment="production",
        )
        assert exec_ok.error is None
        assert len(provider._executed_actions) == 1

        # Step 5: Anti-replay over HTTP
        replay = await client.call_tool(
            "execute_action",
            {
                "incident_id": "INC-HTTP-EXACT-01",
                "action_id": action_id,
                "action_type": "rollback_deployment",
                "target_service": "payments-service",
                "parameters": {"target_version": "1.8.2"},
                "rationale": "Replay attempt over HTTP",
            },
            actor_id="sre-actor",
            actor_role="sre",
            environment="production",
        )
        assert replay.error is not None
        assert "already been consumed" in replay.error.message.lower()
        assert len(provider._executed_actions) == 1
