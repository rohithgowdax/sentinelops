"""
Telemetry Evidence Capability Provider for SentinelOps.

Implements `TelemetryEvidenceProvider` protocol by wrapping `OperationalStore`.
Translates low-level historical metric queries into high-level structured evidence
consumed by the LangGraph AI investigation agent.

Architectural Rule:
Agent nodes must NEVER execute raw SQL or direct store queries.
They call this capability boundary.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from sentinelops.domain.contracts.protocols import OperationalStore, TelemetryEvidenceProvider
from sentinelops.domain.models.incident import Incident

log = structlog.get_logger(__name__)


class PostgresTelemetryEvidenceProvider:
    """
    Production TelemetryEvidenceProvider wrapping the OperationalStore persistence layer.
    """

    def __init__(self, store: OperationalStore) -> None:
        """
        Initialize the evidence provider.

        Args:
            store: `OperationalStore` repository implementation.
        """
        self._store = store

    async def query_recent_telemetry(
        self,
        service_name: str,
        metric_name: str,
        lookback_seconds: int = 300,
    ) -> dict[str, Any]:
        """
        Query recent canonical telemetry data points for a service and metric.

        Args:
            service_name: Name of target service (e.g. 'payments-service').
            metric_name: Canonical metric name (e.g. 'http.error_rate').
            lookback_seconds: Window duration in seconds (default: 300s).

        Returns:
            Structured dictionary with summary observations and raw references.
        """
        now = datetime.now(tz=timezone.utc)
        since = now - timedelta(seconds=lookback_seconds)

        records = await self._store.query_recent_metrics(
            service_name=service_name,
            metric_name=metric_name,
            since=since,
        )

        values = [r.metric.value for r in records if r.metric and r.metric.value is not None]

        if not values:
            return {
                "resource": service_name,
                "metric": metric_name,
                "window": {"start": since.isoformat(), "end": now.isoformat()},
                "sample_count": 0,
                "observed_avg": None,
                "observed_max": None,
                "observed_min": None,
                "latest_value": None,
                "raw_references": [],
            }

        return {
            "resource": service_name,
            "metric": metric_name,
            "window": {"start": since.isoformat(), "end": now.isoformat()},
            "sample_count": len(values),
            "observed_avg": round(statistics.mean(values), 4),
            "observed_max": round(max(values), 4),
            "observed_min": round(min(values), 4),
            "latest_value": round(values[-1], 4),
            "raw_references": [r.event_id for r in records[:5]],
        }

    async def compare_telemetry_baseline(
        self,
        service_name: str,
        metric_name: str,
        current_window_seconds: int = 120,
        baseline_window_seconds: int = 600,
    ) -> dict[str, Any]:
        """
        Compare current metric behavior against historical baseline.

        Args:
            service_name: Name of target service.
            metric_name: Canonical metric name.
            current_window_seconds: Window duration for current degraded state.
            baseline_window_seconds: Window duration for historical baseline state.

        Returns:
            Structured comparison dictionary with baseline, current average, and ratio.
        """
        now = datetime.now(tz=timezone.utc)
        current_since = now - timedelta(seconds=current_window_seconds)
        baseline_since = now - timedelta(seconds=baseline_window_seconds)

        # Query all records across the full duration
        all_records = await self._store.query_recent_metrics(
            service_name=service_name,
            metric_name=metric_name,
            since=baseline_since,
        )

        # Split into baseline records and current records
        baseline_vals: list[float] = []
        current_vals: list[float] = []

        for r in all_records:
            if not r.metric or r.metric.value is None:
                continue
            if r.timestamp >= current_since:
                current_vals.append(r.metric.value)
            else:
                baseline_vals.append(r.metric.value)

        baseline_avg = round(statistics.mean(baseline_vals), 4) if baseline_vals else 0.0
        current_avg = round(statistics.mean(current_vals), 4) if current_vals else 0.0

        if baseline_avg > 0:
            elevation_ratio = round(current_avg / baseline_avg, 2)
        elif current_avg > 0:
            elevation_ratio = round(current_avg / 0.01, 2)
        else:
            elevation_ratio = 1.0

        return {
            "resource": service_name,
            "metric": metric_name,
            "baseline_window": {
                "start": baseline_since.isoformat(),
                "end": current_since.isoformat(),
            },
            "current_window": {
                "start": current_since.isoformat(),
                "end": now.isoformat(),
            },
            "baseline_avg": baseline_avg,
            "current_avg": current_avg,
            "elevation_ratio": elevation_ratio,
            "is_elevated": elevation_ratio > 1.5,
            "baseline_samples": len(baseline_vals),
            "current_samples": len(current_vals),
        }

    async def get_incident_trigger_context(
        self,
        incident: Incident,
    ) -> dict[str, Any]:
        """
        Extract structured trigger context and initial evidence from canonical incident.

        Args:
            incident: Canonical `Incident` domain model.

        Returns:
            Structured dictionary of trigger parameters and observations.
        """
        return {
            "incident_id": incident.incident_id,
            "service_name": incident.service_name,
            "environment": incident.environment,
            "severity": incident.severity.value,
            "trigger_rule_id": incident.trigger_rule_id,
            "trigger_rule_name": incident.trigger_rule_name,
            "trigger_type": incident.trigger_type.value,
            "episode_key": incident.episode_key,
            "context": incident.context,
            "initial_evidence": [e.model_dump() for e in incident.initial_evidence],
        }
