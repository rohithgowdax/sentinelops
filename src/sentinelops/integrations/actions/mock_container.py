"""
Mock Container ActionProvider for SentinelOps.

Simulates container / pod orchestration (image tag updates, container restarts, pod scaling)
in a stateful, deterministic mock environment.

Implements the exact same `ActionProvider` protocol as `MockServiceDeploymentProvider`,
proving provider neutrality across infrastructure substrates.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sentinelops.capabilities.actions.protocol import (
    ActionProvider,
    ActionValidationResult,
)
from sentinelops.domain.models.action import (
    ActionRequest,
    ActionResult,
    ActionStatus,
    ActionType,
)

logger = logging.getLogger(__name__)


class MockContainerProvider:
    """
    Mock implementation of ActionProvider simulating container/pod management.
    """

    def __init__(self, initial_state: dict[str, Any] | None = None) -> None:
        self._provider_name = "mock_container_provider"
        # State: container_id -> container attributes
        self._containers: dict[str, dict[str, Any]] = initial_state or {
            "payments-service": {
                "image_tag": "v1.8.3",
                "container_status": "Degraded",
                "restart_count": 8,
                "metrics": {
                    "http.error_rate": 0.184,
                    "http.server.duration_p99": 4.80,
                    "db.pool.active_connections": 96.0,
                },
            },
            "order-service": {
                "image_tag": "v2.1.0",
                "container_status": "CrashLoopBackOff",
                "restart_count": 14,
                "metrics": {
                    "http.error_rate": 0.142,
                    "jvm.memory.used_percent": 0.94,
                    "http.server.duration_p99": 3.60,
                },
            },
        }
        self._executed_actions: dict[str, ActionResult] = {}

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def get_container_state(self, container_id: str) -> dict[str, Any] | None:
        c = self._containers.get(container_id)
        return dict(c) if c else None

    async def validate(self, request: ActionRequest) -> ActionValidationResult:
        target_id = request.target.resource_id
        if target_id not in self._containers:
            return ActionValidationResult(
                is_valid=False,
                reason=f"Container workload '{target_id}' not found in cluster namespace.",
                target_exists=False,
                parameters_valid=False,
            )

        container = self._containers[target_id]

        if request.action_type == ActionType.ROLLBACK_DEPLOYMENT:
            target_version = request.parameters.get("target_version")
            if not target_version:
                return ActionValidationResult(
                    is_valid=False,
                    reason="Missing 'target_version' image tag parameter for rollback.",
                    target_exists=True,
                    parameters_valid=False,
                )
            return ActionValidationResult(
                is_valid=True,
                reason="Container workload found and rollback image tag valid.",
                target_exists=True,
                parameters_valid=True,
            )

        elif request.action_type in (ActionType.RESTART_SERVICE, ActionType.SCALE_SERVICE):
            return ActionValidationResult(
                is_valid=True,
                reason=f"Container workload found and {request.action_type.value} is supported.",
                target_exists=True,
                parameters_valid=True,
            )

        return ActionValidationResult(
            is_valid=False,
            reason=f"Unsupported container action type: {request.action_type}",
            target_exists=True,
            parameters_valid=False,
        )

    async def execute(self, request: ActionRequest) -> ActionResult:
        # Idempotency check
        if request.action_id in self._executed_actions:
            logger.info("Container action %s already executed. Returning cached result.", request.action_id)
            return self._executed_actions[request.action_id]

        validation = await self.validate(request)
        if not validation.is_valid:
            failed_res = ActionResult(
                action_id=request.action_id,
                status=ActionStatus.REJECTED,
                provider=self.provider_name,
                completed_at=datetime.now(tz=timezone.utc),
                error=validation.reason,
            )
            self._executed_actions[request.action_id] = failed_res
            return failed_res

        target_id = request.target.resource_id
        container = self._containers[target_id]
        started_at = datetime.now(tz=timezone.utc)

        if request.action_type == ActionType.ROLLBACK_DEPLOYMENT:
            old_tag = container["image_tag"]
            new_tag = request.parameters["target_version"]
            container["image_tag"] = new_tag
            container["container_status"] = "Running"
            if "http.error_rate" in container["metrics"]:
                container["metrics"]["http.error_rate"] = 0.007
            if "http.server.duration_p99" in container["metrics"]:
                container["metrics"]["http.server.duration_p99"] = 0.41
            if "db.pool.active_connections" in container["metrics"]:
                container["metrics"]["db.pool.active_connections"] = 42.0

            result_data = {
                "container_id": target_id,
                "previous_image_tag": old_tag,
                "new_image_tag": new_tag,
                "status": "Running",
                "message": f"Pod container {target_id} updated to image tag {new_tag}.",
            }

        elif request.action_type == ActionType.RESTART_SERVICE:
            container["container_status"] = "Running"
            container["restart_count"] += 1
            if "http.error_rate" in container["metrics"]:
                container["metrics"]["http.error_rate"] = 0.005
            if "http.server.duration_p99" in container["metrics"]:
                container["metrics"]["http.server.duration_p99"] = 0.38

            result_data = {
                "container_id": target_id,
                "status": "Running",
                "message": f"Pod container {target_id} restarted cleanly.",
            }

        elif request.action_type == ActionType.SCALE_SERVICE:
            replicas = request.parameters.get("replicas", 2)
            if "http.error_rate" in container["metrics"]:
                container["metrics"]["http.error_rate"] = 0.006
            if "http.server.duration_p99" in container["metrics"]:
                container["metrics"]["http.server.duration_p99"] = 0.35
            result_data = {
                "container_id": target_id,
                "status": "Running",
                "replicas": replicas,
                "message": f"Pod deployment scaled to {replicas} replicas.",
            }
        else:
            raise ValueError(f"Unhandled action type: {request.action_type}")

        action_result = ActionResult(
            action_id=request.action_id,
            status=ActionStatus.SUCCEEDED,
            provider=self.provider_name,
            started_at=started_at,
            completed_at=datetime.now(tz=timezone.utc),
            result=result_data,
            metadata={"container_metrics": dict(container["metrics"])},
        )

        self._executed_actions[request.action_id] = action_result
        return action_result
