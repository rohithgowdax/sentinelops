"""
Mock Service Deployment ActionProvider for SentinelOps.

Simulates deployment lifecycle management (rollbacks, restarts, scaling) in a stateful,
deterministic mock environment.

Invariants:
- Never executes real system or cloud commands.
- Implements strict idempotency using `action_id`.
- Mutates simulated resource state and telemetry upon successful execution.
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


class MockServiceDeploymentProvider:
    """
    Mock implementation of ActionProvider simulating service deployment orchestration.
    """

    def __init__(self, initial_state: dict[str, Any] | None = None) -> None:
        self._provider_name = "mock_service_deployment_provider"
        # State: service_name -> resource attributes
        self._resources: dict[str, dict[str, Any]] = initial_state or {
            "payments-service": {
                "current_version": "1.8.3",
                "status": "degraded",
                "replicas": 4,
                "metrics": {
                    "http.error_rate": 0.184,
                    "http.server.duration_p99": 4.80,
                    "db.pool.active_connections": 96.0,
                },
            },
            "order-service": {
                "current_version": "2.1.0",
                "status": "degraded",
                "replicas": 3,
                "metrics": {
                    "http.error_rate": 0.142,
                    "jvm.memory.used_percent": 0.94,
                    "http.server.duration_p99": 3.60,
                },
            },
            "auth-service": {
                "current_version": "1.4.2",
                "status": "degraded",
                "replicas": 2,
                "metrics": {
                    "cache.eviction_rate": 1850.0,
                    "http.error_rate": 0.120,
                },
            },
            "checkout-service": {
                "current_version": "3.0.1",
                "status": "degraded",
                "replicas": 5,
                "metrics": {
                    "http.error_rate": 0.165,
                    "http.server.duration_p99": 2.90,
                },
            },
        }
        # Idempotency tracking: action_id -> ActionResult
        self._executed_actions: dict[str, ActionResult] = {}

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def get_resource_state(self, service_name: str) -> dict[str, Any] | None:
        """Return the current simulated state of a resource."""
        res = self._resources.get(service_name)
        return dict(res) if res else None

    async def validate(self, request: ActionRequest) -> ActionValidationResult:
        """
        Validate target resource existence and action parameter sanity before execution.
        """
        target_id = request.target.resource_id
        if target_id not in self._resources:
            return ActionValidationResult(
                is_valid=False,
                reason=f"Target service '{target_id}' does not exist in deployment registry.",
                target_exists=False,
                parameters_valid=False,
            )

        resource = self._resources[target_id]

        if request.action_type == ActionType.ROLLBACK_DEPLOYMENT:
            target_version = request.parameters.get("target_version")
            if not target_version:
                return ActionValidationResult(
                    is_valid=False,
                    reason="Missing required parameter 'target_version' for rollback.",
                    target_exists=True,
                    parameters_valid=False,
                )
            if target_version == resource["current_version"]:
                return ActionValidationResult(
                    is_valid=False,
                    reason=f"Target version '{target_version}' is already the active version.",
                    target_exists=True,
                    parameters_valid=False,
                )
            return ActionValidationResult(
                is_valid=True,
                reason="Target service exists and rollback target version is valid.",
                target_exists=True,
                parameters_valid=True,
            )

        elif request.action_type == ActionType.RESTART_SERVICE:
            return ActionValidationResult(
                is_valid=True,
                reason="Target service exists and restart operation is valid.",
                target_exists=True,
                parameters_valid=True,
            )

        elif request.action_type == ActionType.SCALE_SERVICE:
            replicas = request.parameters.get("replicas")
            if replicas is None or not isinstance(replicas, int) or replicas <= 0:
                return ActionValidationResult(
                    is_valid=False,
                    reason="Parameter 'replicas' must be a positive integer.",
                    target_exists=True,
                    parameters_valid=False,
                )
            return ActionValidationResult(
                is_valid=True,
                reason="Target service exists and scale parameters are valid.",
                target_exists=True,
                parameters_valid=True,
            )

        return ActionValidationResult(
            is_valid=False,
            reason=f"Unsupported action type: {request.action_type}",
            target_exists=True,
            parameters_valid=False,
        )

    async def execute(self, request: ActionRequest) -> ActionResult:
        """
        Execute the validated action idempotently on the simulated deployment environment.
        """
        # Idempotency check: if already executed, return cached outcome
        if request.action_id in self._executed_actions:
            logger.info("Action %s already executed. Returning cached result (idempotency).", request.action_id)
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
        resource = self._resources[target_id]
        started_at = datetime.now(tz=timezone.utc)

        # Apply state changes to simulated infrastructure
        if request.action_type == ActionType.ROLLBACK_DEPLOYMENT:
            previous_version = resource["current_version"]
            new_version = request.parameters["target_version"]
            resource["current_version"] = new_version
            resource["status"] = "healthy"
            # Simulated telemetry reflects recovery
            if "http.error_rate" in resource["metrics"]:
                resource["metrics"]["http.error_rate"] = 0.007
            if "http.server.duration_p99" in resource["metrics"]:
                resource["metrics"]["http.server.duration_p99"] = 0.41
            if "db.pool.active_connections" in resource["metrics"]:
                resource["metrics"]["db.pool.active_connections"] = 42.0

            result_data = {
                "previous_version": previous_version,
                "current_version": new_version,
                "status": "healthy",
                "message": f"Successfully rolled back {target_id} from {previous_version} to {new_version}.",
            }

        elif request.action_type == ActionType.RESTART_SERVICE:
            resource["status"] = "healthy"
            if "http.error_rate" in resource["metrics"]:
                resource["metrics"]["http.error_rate"] = 0.005
            if "http.server.duration_p99" in resource["metrics"]:
                resource["metrics"]["http.server.duration_p99"] = 0.38
            if "jvm.memory.used_percent" in resource["metrics"]:
                resource["metrics"]["jvm.memory.used_percent"] = 0.38
            if "cache.eviction_rate" in resource["metrics"]:
                resource["metrics"]["cache.eviction_rate"] = 45.0
            if "db.pool.active_connections" in resource["metrics"]:
                resource["metrics"]["db.pool.active_connections"] = 40.0

            result_data = {
                "service": target_id,
                "status": "healthy",
                "message": f"Service {target_id} restarted cleanly.",
            }

        elif request.action_type == ActionType.SCALE_SERVICE:
            new_replicas = request.parameters["replicas"]
            old_replicas = resource["replicas"]
            resource["replicas"] = new_replicas
            resource["status"] = "healthy"
            if "http.server.duration_p99" in resource["metrics"]:
                resource["metrics"]["http.server.duration_p99"] = 0.35
            if "http.error_rate" in resource["metrics"]:
                resource["metrics"]["http.error_rate"] = 0.006

            result_data = {
                "service": target_id,
                "previous_replicas": old_replicas,
                "current_replicas": new_replicas,
                "status": "healthy",
                "message": f"Scaled {target_id} from {old_replicas} to {new_replicas} replicas.",
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
            metadata={"simulated_metrics": dict(resource["metrics"])},
        )

        self._executed_actions[request.action_id] = action_result
        return action_result
