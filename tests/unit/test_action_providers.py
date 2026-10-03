"""
Unit Tests for ActionProvider Implementations.
"""
from __future__ import annotations

import pytest

from sentinelops.domain.models.action import (
    ActionRequest,
    ActionStatus,
    ActionType,
    TargetResource,
)
from sentinelops.integrations.actions.mock_container import MockContainerProvider
from sentinelops.integrations.actions.mock_deployment import (
    MockServiceDeploymentProvider,
)


class TestMockServiceDeploymentProvider:
    @pytest.mark.asyncio
    async def test_validation_rejects_nonexistent_service(self) -> None:
        provider = MockServiceDeploymentProvider()
        req = ActionRequest(
            incident_id="INC-1",
            action_type=ActionType.ROLLBACK_DEPLOYMENT,
            target=TargetResource(resource_type="service", resource_id="nonexistent-svc"),
            parameters={"target_version": "1.0.0"},
            rationale="test",
        )
        val = await provider.validate(req)
        assert val.is_valid is False
        assert "does not exist" in val.reason

    @pytest.mark.asyncio
    async def test_validation_rejects_missing_version(self) -> None:
        provider = MockServiceDeploymentProvider()
        req = ActionRequest(
            incident_id="INC-1",
            action_type=ActionType.ROLLBACK_DEPLOYMENT,
            target=TargetResource(resource_type="service", resource_id="payments-service"),
            parameters={},  # Missing target_version
            rationale="test",
        )
        val = await provider.validate(req)
        assert val.is_valid is False
        assert "Missing required parameter" in val.reason

    @pytest.mark.asyncio
    async def test_execution_updates_state_and_telemetry(self) -> None:
        provider = MockServiceDeploymentProvider()
        req = ActionRequest(
            action_id="ACT-101",
            incident_id="INC-101",
            action_type=ActionType.ROLLBACK_DEPLOYMENT,
            target=TargetResource(resource_type="service", resource_id="payments-service"),
            parameters={"target_version": "1.8.2"},
            rationale="Rollback to stable version",
        )
        res = await provider.execute(req)
        assert res.status == ActionStatus.SUCCEEDED
        assert res.action_id == "ACT-101"
        assert res.result["previous_version"] == "1.8.3"
        assert res.result["current_version"] == "1.8.2"

        # Verify simulated state changed
        state = provider.get_resource_state("payments-service")
        assert state is not None
        assert state["current_version"] == "1.8.2"
        assert state["status"] == "healthy"
        assert state["metrics"]["http.error_rate"] == 0.007
        assert state["metrics"]["http.server.duration_p99"] == 0.41

    @pytest.mark.asyncio
    async def test_idempotency_returns_cached_result(self) -> None:
        provider = MockServiceDeploymentProvider()
        req = ActionRequest(
            action_id="ACT-DUP-01",
            incident_id="INC-1",
            action_type=ActionType.ROLLBACK_DEPLOYMENT,
            target=TargetResource(resource_type="service", resource_id="payments-service"),
            parameters={"target_version": "1.8.2"},
            rationale="Initial execution",
        )
        res1 = await provider.execute(req)
        assert res1.status == ActionStatus.SUCCEEDED

        # Duplicate delivery with identical action_id
        res2 = await provider.execute(req)
        assert res2.status == ActionStatus.SUCCEEDED
        assert res2.action_id == res1.action_id
        assert res2.started_at == res1.started_at


class TestMockContainerProvider:
    @pytest.mark.asyncio
    async def test_container_execution_and_idempotency(self) -> None:
        provider = MockContainerProvider()
        req = ActionRequest(
            action_id="ACT-CONT-01",
            incident_id="INC-201",
            action_type=ActionType.ROLLBACK_DEPLOYMENT,
            target=TargetResource(resource_type="container", resource_id="payments-service"),
            parameters={"target_version": "v1.8.2"},
            rationale="Rollback pod container image tag",
        )
        val = await provider.validate(req)
        assert val.is_valid is True

        res1 = await provider.execute(req)
        assert res1.status == ActionStatus.SUCCEEDED
        assert res1.result["new_image_tag"] == "v1.8.2"

        c_state = provider.get_container_state("payments-service")
        assert c_state is not None
        assert c_state["image_tag"] == "v1.8.2"
        assert c_state["container_status"] == "Running"

        # Idempotency
        res2 = await provider.execute(req)
        assert res2.started_at == res1.started_at
