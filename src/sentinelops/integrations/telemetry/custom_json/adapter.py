"""
Adapter B: Custom JSON telemetry adapter.

Maps a deliberately different non-OTel JSON format into canonical `TelemetryRecord` objects.

Sample External Payload:
{
  "svc": "payments-service",
  "env": "production",
  "metric_name": "err_pct",
  "metric_value": 18.4,
  "unit": "percent",
  "time": "2026-10-01T14:37:12Z",
  "tags": {"region": "us-east-1"},
  "src_id": "custom-agent-001"
}

Architectural Role:
This adapter demonstrates the Generalization Proof of SentinelOps.
It accepts completely different field names (svc vs service.name, metric_name vs name,
tags vs dimensions, percent 0-100 vs ratio 0-1) and maps them into the EXACT same
canonical model produced by `OtelLikeAdapter`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from sentinelops.domain.contracts.protocols import TelemetryAdapter
from sentinelops.domain.models.telemetry import (
    MetricObservation,
    ResourceIdentity,
    SignalType,
    TelemetryRecord,
    TelemetrySource,
)

# Initialize logger
log = structlog.get_logger(__name__)

# Constants defining provider metadata
_PROVIDER = "custom_json"
_INTEGRATION_ID = "custom-json-v1"

# Internal adapter mapping table: Custom Metric Names -> Canonical Metric Names
# NOTE: This lookup table lives ONLY inside this adapter module, NEVER in core engine code.
_METRIC_NAME_MAP: dict[str, str] = {
    "err_pct": "http.error_rate",
    "lat_p99_ms": "http.latency.p99",
    "req_per_sec": "http.request_rate",
    "err_total": "http.error_total",
    "error_rate": "http.error_rate",
    "latency_p99": "http.latency.p99",
}


def _canonical_metric_name(raw_name: str) -> str:
    """
    Map a custom metric name to its canonical equivalent, or pass through if unmapped.

    Args:
        raw_name: Metric name string from external custom JSON (e.g. 'err_pct').

    Returns:
        Canonical metric name string (e.g. 'http.error_rate').
    """
    return _METRIC_NAME_MAP.get(raw_name, raw_name)


def _parse_timestamp(value: str | int | float) -> datetime:
    """
    Parse ISO 8601 string or numeric Unix epoch timestamp into UTC datetime.

    Args:
        value: ISO 8601 string (e.g. '2026-10-01T14:37:12Z') or float timestamp.

    Returns:
        Timezone-aware UTC datetime.
    """
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    # Parse ISO 8601 string, supporting standard Z suffix
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class CustomJsonAdapter:
    """
    Adapter implementation for custom JSON telemetry payloads.

    Implements `TelemetryAdapter` protocol. Handles field normalization, name mapping,
    and unit scaling (converting percentage values 0..100 to ratio 0..1).
    """

    @property
    def provider(self) -> str:
        """Returns the logical provider identifier ('custom_json')."""
        return _PROVIDER

    @property
    def integration_id(self) -> str:
        """Returns the specific adapter instance identifier ('custom-json-v1')."""
        return _INTEGRATION_ID

    def normalize(self, raw: dict[str, Any]) -> TelemetryRecord:
        """
        Normalize a raw custom JSON dictionary into a canonical TelemetryRecord.

        Steps:
        1. Validate presence of required keys ('svc', 'metric_name', 'metric_value').
        2. Extract resource metadata ('svc' -> service_name, 'env' -> environment, etc.).
        3. Parse timestamp into UTC datetime.
        4. Map custom metric name (e.g. 'err_pct' -> 'http.error_rate').
        5. Normalize percentage values (e.g. 18.4% -> 0.184 ratio).
        6. Construct canonical ResourceIdentity, MetricObservation, and TelemetryRecord.

        Args:
            raw: Python dictionary parsed from incoming custom JSON.

        Returns:
            Normalized canonical TelemetryRecord.

        Raises:
            ValueError: If required fields are missing or numeric values/timestamps cannot be parsed.
        """
        # Step 1: Validate required fields
        missing = [f for f in ("svc", "metric_name", "metric_value") if f not in raw]
        if missing:
            raise ValueError(
                f"CustomJsonAdapter: missing required fields: {missing}. "
                f"Got keys: {list(raw.keys())}"
            )

        # Step 2: Extract resource identification fields
        service_name: str = str(raw["svc"])
        environment: str | None = raw.get("env") or raw.get("environment")
        namespace: str | None = raw.get("ns") or raw.get("namespace")
        version: str | None = raw.get("ver") or raw.get("version")
        host: str | None = raw.get("host")

        # Step 3: Parse timestamp (default to now if omitted)
        ts_raw = raw.get("time") or raw.get("timestamp")
        if ts_raw is not None:
            try:
                ts = _parse_timestamp(ts_raw)
            except (ValueError, OSError) as exc:
                raise ValueError(
                    f"CustomJsonAdapter: cannot parse timestamp '{ts_raw}': {exc}"
                ) from exc
        else:
            ts = datetime.now(tz=timezone.utc)

        # Step 4: Map raw metric name to canonical metric name
        raw_metric_name = str(raw["metric_name"])
        canonical_name = _canonical_metric_name(raw_metric_name)

        # Step 5: Validate and parse numeric metric value
        try:
            value = float(raw["metric_value"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"CustomJsonAdapter: metric_value must be numeric, got '{raw['metric_value']}': {exc}"
            ) from exc

        unit: str | None = raw.get("unit")

        # Step 6: Extract label dimensions
        tags: dict[str, Any] = raw.get("tags", {})
        dimensions: dict[str, str] = {str(k): str(v) for k, v in tags.items()}

        # Step 7: Unit Normalization
        # If the metric is a percentage expressed on a 0-100 scale (e.g. 18.4%),
        # scale it down to a 0-1 ratio (0.184) to match canonical OTel conventions.
        if unit in ("percent", "%") and value > 1.0:
            value = value / 100.0
            unit = "ratio"

        # Step 8: Assemble canonical models
        resource = ResourceIdentity(
            service_name=service_name,
            service_namespace=namespace,
            service_version=version,
            environment=environment,
            host_name=host,
        )

        metric = MetricObservation(
            name=canonical_name,
            value=value,
            unit=unit,
            dimensions=dimensions,
        )

        # Allow per-event override of integration source ID if specified in payload
        src_id: str = str(raw.get("src_id", _INTEGRATION_ID))

        # Return full canonical TelemetryRecord envelope
        return TelemetryRecord(
            event_id=str(raw.get("event_id", str(uuid.uuid4()))),
            timestamp=ts,
            signal_type=SignalType.METRIC,
            source=TelemetrySource(
                provider=self.provider,
                integration_id=src_id,
            ),
            resource=resource,
            metric=metric,
            attributes={},
            raw_payload=raw,  # Retain raw payload for debugging
        )
