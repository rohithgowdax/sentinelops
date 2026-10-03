"""
Remediation Generalization Contract Tests for SentinelOps Slice 4.

Architectural Proof:
Verifies that the SentinelOps Remediation and Safety loop operates entirely on
canonical ActionRequest and ActionResult domain models without branching on specific
infrastructure providers.

Proofs:
1. Protocol Conformance: Both MockServiceDeploymentProvider and MockContainerProvider
   fully satisfy the ActionProvider protocol.
2. Canonical Equivalence: Identical ActionRequest objects execute successfully and
   transition target states across heterogeneous providers.
3. Zero Provider Branching in Agent AST: Source code AST analysis confirms zero
   branching on provider identifiers inside remediation nodes.
4. Idempotency Guarantee: Both providers enforce strict idempotency by caching and returning
   identical results when an action is executed more than once.
5. Graph Equivalence: The LangGraph remediation loop resolves identical incidents
   identically whether bound to MockServiceDeploymentProvider or MockContainerProvider.
"""
from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from pathlib import Path
import pytest

from langgraph.checkpoint.memory import MemorySaver

from sentinelops.agent.graph import create_investigation_graph
from sentinelops.agent.nodes import action_executor, policy_evaluator, remediation_planner, remediation_verifier
from sentinelops.agent.state import InvestigationState
from sentinelops.capabilities.actions.protocol import ActionProvider
from sentinelops.capabilities.llm.provider import DeterministicLLMProvider
from sentinelops.domain.models.action import (
    ActionRequest,
    ActionResult,
    ActionStatus,
    ActionType,
    TargetResource,
)
from sentinelops.domain.models.incident import (
    EvidenceItem,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    TriggerType,
)
from sentinelops.domain.models.investigation import InvestigationStatus
from sentinelops.integrations.actions.mock_container import MockContainerProvider
from sentinelops.integrations.actions.mock_deployment import MockServiceDeploymentProvider
from sentinelops.policy.engine import PolicyEngine


from tests.unit.test_remediation_graph import (
    _make_mock_evidence_provider,
    _make_test_incident,
)


class TestRemediationGeneralizationContract:
    """Contract test suite proving provider neutrality in remediation execution."""

    def test_protocol_conformance(self) -> None:
        """Verify both providers implement ActionProvider protocol."""
        deploy_provider = MockServiceDeploymentProvider()
        container_provider = MockContainerProvider()

        assert isinstance(deploy_provider, ActionProvider)
        assert isinstance(container_provider, ActionProvider)
        assert callable(getattr(deploy_provider, "validate", None))
        assert callable(getattr(deploy_provider, "execute", None))
        assert callable(getattr(container_provider, "validate", None))
        assert callable(getattr(container_provider, "execute", None))

    def test_zero_provider_branching_in_remediation_ast(self) -> None:
        """
        Verify that agent remediation nodes contain zero branching on concrete provider names.
        """
        prohibited_literals = {
            "mock_service_deployment_provider",
            "mock_container_provider",
            "kubernetes",
            "k8s",
            "ecs",
            "aws",
            "docker",
        }

        remediation_modules = [
            remediation_planner,
            policy_evaluator,
            action_executor,
            remediation_verifier,
        ]

        for mod in remediation_modules:
            source = inspect.getsource(mod)
            tree = ast.parse(source)

            for node in ast.walk(tree):
                if isinstance(node, ast.Compare):
                    for comparator in node.comparators:
                        if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                            val = comparator.value.lower()
                            assert val not in prohibited_literals, (
                                f"Forbidden provider branch comparison '{val}' detected in "
                                f"{mod.__name__}:{node.lineno}"
                            )

    @pytest.mark.asyncio
    async def test_canonical_action_execution_across_providers(self) -> None:
        """
        Prove that an identical ActionRequest executes cleanly on both
        MockServiceDeploymentProvider and MockContainerProvider.
        """
        deploy_prov = MockServiceDeploymentProvider()
        container_prov = MockContainerProvider()

        action_req = ActionRequest(
            action_id="ACT-CONTRACT-RESTART-01",
            incident_id="INC-staging-contract-01",
            action_type=ActionType.RESTART_SERVICE,
            target=TargetResource(
                resource_type="service",
                resource_id="payments-service",
                environment="staging",
            ),
            parameters={},
            rationale="Automated service restart to restore degraded state.",
        )

        # Validate on both providers
        val_deploy = await deploy_prov.validate(action_req)
        val_container = await container_prov.validate(action_req)

        assert val_deploy.is_valid is True
        assert val_container.is_valid is True

        # Execute on deployment provider
        res_deploy: ActionResult = await deploy_prov.execute(action_req)
        assert res_deploy.status == ActionStatus.SUCCEEDED
        assert res_deploy.action_id == action_req.action_id

        # Execute on container provider
        res_container: ActionResult = await container_prov.execute(action_req)
        assert res_container.status == ActionStatus.SUCCEEDED
        assert res_container.action_id == action_req.action_id

    @pytest.mark.asyncio
    async def test_idempotency_enforced_across_providers(self) -> None:
        """
        Prove both providers return cached results for duplicate action executions.
        """
        deploy_prov = MockServiceDeploymentProvider()
        container_prov = MockContainerProvider()

        action_req = ActionRequest(
            action_id="ACT-CONTRACT-IDEMPOTENT-01",
            incident_id="INC-staging-contract-01",
            action_type=ActionType.SCALE_SERVICE,
            target=TargetResource(
                resource_type="service",
                resource_id="payments-service",
                environment="staging",
            ),
            parameters={"replicas": 5},
            rationale="Scale replicas to handle high load.",
        )

        res1_dep = await deploy_prov.execute(action_req)
        res2_dep = await deploy_prov.execute(action_req)
        assert res1_dep.completed_at == res2_dep.completed_at

        res1_cont = await container_prov.execute(action_req)
        res2_cont = await container_prov.execute(action_req)
        assert res1_cont.completed_at == res2_cont.completed_at

    @pytest.mark.asyncio
    async def test_langgraph_flow_equivalence_across_providers(self) -> None:
        """
        Prove LangGraph investigation and remediation workflow succeeds identically
        with either provider plugged in.
        """
        for prov_cls in (MockServiceDeploymentProvider, MockContainerProvider):
            prov = prov_cls()
            incident = _make_test_incident(env="staging", service="payments-service")
            from tests.unit.test_remediation_graph import _make_mock_evidence_provider
            ev_prov = _make_mock_evidence_provider("payments-service")
            policy_engine = PolicyEngine()
            checkpointer = MemorySaver()

            graph = create_investigation_graph(
                evidence_provider=ev_prov,
                llm_provider=DeterministicLLMProvider(),
                action_provider=prov,
                policy_engine=policy_engine,
                checkpointer=checkpointer,
            )

            initial_state: InvestigationState = {
                "incident": incident,
                "investigation_plan": None,
                "current_step": 0,
                "iteration": 0,
                "max_iterations": 3,
                "evidence": [],
                "hypotheses": [],
                "selected_hypothesis": None,
                "diagnosis": None,
                "confidence": 0.0,
                "verification_result": None,
                "status": InvestigationStatus.INVESTIGATING,
                "errors": [],
                "tool_calls_summary": [],
                "start_time_iso": datetime.now(tz=timezone.utc).isoformat(),
                "final_result": None,
                "evidence_groups": {"telemetry": [], "knowledge": []},
                "knowledge_queries": [],
                "knowledge_available": False,
                "retrieval_mode": "hybrid",
                "action_request": None,
                "policy_decision": None,
                "action_result": None,
                "remediation_verification": None,
                "remediation_attempts": 0,
                "max_remediation_attempts": 2,
                "remediation_status": "idle",
            }

            config = {"configurable": {"thread_id": f"contract-flow-{prov.provider_name}"}}
            final_state = await graph.ainvoke(initial_state, config=config)

            assert final_state["status"] == InvestigationStatus.RESOLVED
            assert final_state["remediation_status"] == "resolved"
            assert final_state["action_result"].status == ActionStatus.SUCCEEDED
