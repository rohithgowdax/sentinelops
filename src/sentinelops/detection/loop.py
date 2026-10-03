"""
Periodic Detection Loop Orchestrator for SentinelOps.

Role:
Continuously queries the `OperationalStore` for recent canonical telemetry metrics and evaluates loaded
`DetectionRule` configs via `evaluate_rule()`. When a rule fires:
1. Checks `OperationalStore.get_active_episode(episode_key)` for active duplicate incidents.
2. Constructs a new canonical `Incident` if no active episode exists.
3. Saves the `Incident` to `OperationalStore`.
4. Publishes `IncidentCreatedEvent` to `EventBus` ('sentinel:incidents' stream).

Deduplication Mechanism:
The `episode_key` ('rule_id::service::env') ensures that an ongoing outage generates ONLY ONE incident
record, even if the detection loop runs every 10 seconds.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from sentinelops.detection.engine import EvaluationResult, evaluate_rule
from sentinelops.detection.rules import DetectionRule, load_rules
from sentinelops.domain.contracts.protocols import EventBus, OperationalStore
from sentinelops.domain.models.events import IncidentCreatedEvent
from sentinelops.domain.models.incident import (
    EvidenceItem,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    TriggerType,
)

# Initialize logger
log = structlog.get_logger(__name__)


class DetectionLoop:
    """
    Periodic detection loop runner.

    Maintains dependency references to `OperationalStore` and `EventBus` interfaces.
    Operates statelessly regarding episode state (relies on PostgreSQL `OperationalStore` for deduplication).
    """

    def __init__(
        self,
        store: OperationalStore,
        event_bus: EventBus,
        rules_path: str,
        interval_seconds: float = 10.0,
    ) -> None:
        """
        Initialize the Detection Loop service.

        Args:
            store: `OperationalStore` capability implementation.
            event_bus: `EventBus` capability implementation.
            rules_path: File system path to `detection_rules.yaml`.
            interval_seconds: Sleep duration in seconds between detection evaluation cycles.
        """
        self._store = store
        self._event_bus = event_bus
        self._rules_path = rules_path
        self._interval = interval_seconds
        self._rules: list[DetectionRule] = []
        self._running = False

    def reload_rules(self) -> None:
        """
        Reload detection rule definitions from the YAML configuration file.

        Safe to call dynamically at runtime when rule configuration changes.
        """
        self._rules = load_rules(self._rules_path)
        log.info("detection_loop.rules_reloaded", count=len(self._rules))

    async def run_once(self) -> list[Incident]:
        """
        Execute a single evaluation pass over all active detection rules.

        Useful for unit/integration testing without running a continuous sleep loop.

        Returns:
            List of newly created `Incident` entities generated during this pass.
        """
        # Ensure rules are loaded
        if not self._rules:
            self.reload_rules()

        created: list[Incident] = []

        # Evaluate each active rule sequentially
        for rule in self._rules:
            newly_created = await self._evaluate_rule(rule)
            created.extend(newly_created)

        return created

    async def run(self) -> None:
        """
        Start the background continuous detection loop.

        Runs until `stop()` is called. Handles exceptions per cycle to prevent loop crash.
        """
        self._running = True
        self.reload_rules()
        log.info("detection_loop.started", interval_seconds=self._interval)

        while self._running:
            try:
                await self.run_once()
            except Exception as exc:
                log.error("detection_loop.cycle_error", error=str(exc), exc_info=True)
            # Sleep until next evaluation cycle
            await asyncio.sleep(self._interval)

    def stop(self) -> None:
        """Signal the background loop to shut down gracefully after current cycle."""
        self._running = False
        log.info("detection_loop.stopping")

    # ── Private Implementation Helpers ─────────────────────────────────────────

    async def _evaluate_rule(self, rule: DetectionRule) -> list[Incident]:
        """
        Private helper: Evaluates a single `DetectionRule` across target services.

        Steps:
        1. Calculate look-back time bound: `since = now - window_seconds`.
        2. Discover target (service, environment) pairs.
        3. Query `OperationalStore` for recent canonical metrics.
        4. Execute pure `evaluate_rule()` evaluator.
        5. If rule fired, handle episode deduplication and incident creation.

        Args:
            rule: `DetectionRule` instance.

        Returns:
            List of newly generated `Incident` objects.
        """
        # Step 1: Calculate time window start bound
        since = datetime.now(tz=timezone.utc) - timedelta(seconds=rule.window_seconds)

        # Step 2: Determine services to query
        services = await self._discover_services(rule, since)

        created: list[Incident] = []
        for service_name, environment in services:
            # Step 3: Query operational store for canonical metric records
            records = await self._store.query_recent_metrics(
                service_name=service_name,
                metric_name=rule.metric,
                since=since,
            )

            # Step 4: Call pure deterministic evaluation function
            result = evaluate_rule(rule, records, service_name, environment)

            # Step 5: Process fired result
            if result.fired:
                incident = await self._handle_fired_result(result)
                if incident:
                    created.append(incident)

        return created

    async def _discover_services(
        self, rule: DetectionRule, since: datetime
    ) -> list[tuple[str, str | None]]:
        """
        Private helper: Resolves target (service_name, environment) tuples for a rule.

        Args:
            rule: `DetectionRule` object.
            since: UTC datetime window bound.

        Returns:
            List of (service_name, environment) tuples to evaluate.
        """
        service = rule.service_filter
        if not service:
            log.warning(
                "detection_loop.no_service_filter",
                rule_id=rule.rule_id,
                msg="Rule has no service_filter; skipping.",
            )
            return []
        return [(service, rule.environment)]

    async def _handle_fired_result(self, result: EvaluationResult) -> Incident | None:
        """
        Private helper: Processes a fired `EvaluationResult`.

        Deduplication Check:
        Queries `OperationalStore.get_active_episode(episode_key)`.
        If an OPEN or INVESTIGATING incident exists for `episode_key`, creation is SKIPPED.

        Args:
            result: Fired `EvaluationResult` from `evaluate_rule`.

        Returns:
            Newly created `Incident` if created, or `None` if deduplicated.
        """
        # Step 1: Query database for existing active episode
        existing = await self._store.get_active_episode(result.episode_key)
        if existing:
            log.debug(
                "detection_loop.episode_active",
                episode_key=result.episode_key,
                incident_id=existing.incident_id,
            )
            return None  # Deduplicated!

        # Step 2: Construct canonical Incident domain entity
        incident = _build_incident(result)

        # Step 3: Save to OperationalStore database
        await self._store.save_incident(incident)

        # Step 4: Publish IncidentCreatedEvent to EventBus stream ('sentinel:incidents')
        event = IncidentCreatedEvent(incident=incident)
        await self._event_bus.publish_incident(event)

        log.warning(
            "detection_loop.incident_created",
            incident_id=incident.incident_id,
            rule_id=result.rule.rule_id,
            service=incident.service_name,
            observed=result.observed_value,
            severity=incident.severity.value,
        )

        return incident


def _build_incident(result: EvaluationResult) -> Incident:
    """
    Construct a canonical `Incident` domain model from a fired `EvaluationResult`.

    Args:
        result: Fired `EvaluationResult` container.

    Returns:
        Populated `Incident` entity.
    """
    rule = result.rule
    now = datetime.now(tz=timezone.utc)

    # Attach initial telemetry evidence item
    evidence = EvidenceItem(
        kind="metric",
        description=(
            f"Rule '{rule.name}' fired: {rule.metric} "
            f"{rule.operator.value} {rule.threshold} "
            f"(observed={result.observed_value}, samples={result.sample_count})"
        ),
        value=result.observed_value,
        timestamp=result.evaluated_at,
        attributes={
            "rule_id": rule.rule_id,
            "operator": rule.operator.value,
            "threshold": str(rule.threshold),
            "aggregation": rule.aggregation.value,
            "window_seconds": str(rule.window_seconds),
            "sample_count": str(result.sample_count),
        },
    )

    # Deterministic title and description generation
    title = f"[{rule.severity.upper()}] {rule.name} on {result.service_name}"
    description = (
        f"Detection rule '{rule.name}' (ID: {rule.rule_id}) fired for service "
        f"'{result.service_name}'. "
        f"Metric '{rule.metric}' observed value {result.observed_value:.4f} "
        f"exceeded threshold {rule.threshold} "
        f"({rule.operator.value}) over a {rule.window_seconds}s window "
        f"with {result.sample_count} samples."
    )

    return Incident(
        created_at=now,
        updated_at=now,
        severity=IncidentSeverity(rule.severity),
        status=IncidentStatus.OPEN,
        service_name=result.service_name,
        environment=result.environment,
        trigger_type=TriggerType.METRIC_THRESHOLD,
        trigger_rule_id=rule.rule_id,
        trigger_rule_name=rule.name,
        title=title,
        description=description,
        source_provider="sentinelops-detector",
        source_integration_id=rule.rule_id,
        episode_key=result.episode_key,
        initial_evidence=[evidence],
        context={
            "observed_value": result.observed_value,
            "threshold": rule.threshold,
            "window_seconds": rule.window_seconds,
            "sample_count": result.sample_count,
        },
    )
