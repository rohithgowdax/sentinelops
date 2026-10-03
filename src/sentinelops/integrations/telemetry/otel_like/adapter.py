"""
Adapter A: OpenTelemetry-style JSON adapter.

Maps OTel-like JSON payloads into canonical `TelemetryRecord` objects.

Expected External Formats:
1. Full OpenTelemetry Metrics JSON envelope:
   {
     "resourceMetrics": [{
       "resource": {
         "attributes": [
           {"key": "service.name", "value": {"stringValue": "payments"}},
           {"key": "service.namespace", "value": {"stringValue": "commerce"}},
           {"key": "deployment.environment", "value": {"stringValue": "production"}}
         ]
       },
       "scopeMetrics": [{
         "metrics": [{
           "name": "http.error_rate",
           "unit": "ratio",
           "gauge": {
             "dataPoints": [{
               "timeUnixNano": "1727789832000000000",
               "asDouble": 0.18,
               "attributes": [{"key": "http.method", "value": {"stringValue": "POST"}}]
             }]
           }
         }]
       }]
     }]
   }

2. Simplified Single-Metric Shorthand (for fast testing/simulators):
   {
     "resource": { "service.name": "payments", "deployment.environment": "production" },
     "metric": { "name": "http.error_rate", "value": 0.18, "unit": "ratio" },
     "timestamp": "2026-10-01T14:37:12Z"
   }
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

# Initialize structured logger for telemetry parsing
log = structlog.get_logger(__name__)

# Constants defining provider metadata
_PROVIDER = "otel"
_INTEGRATION_ID = "otel-json-v1"


def _parse_otel_attributes(attrs: list[dict[str, Any]]) -> dict[str, str]:
    """
    Helper function to parse OpenTelemetry attribute key-value pairs.

    OpenTelemetry formats attributes as:
    `[{"key": "service.name", "value": {"stringValue": "payments"}}]`

    This helper flattens that structure into a simple Python string dictionary:
    `{"service.name": "payments"}`

    Args:
        attrs: List of attribute dictionaries in OTel key-value format.

    Returns:
        Flattened string-to-string dictionary of key-value pairs.
    """
    result: dict[str, str] = {}
    for attr in attrs:
        key = attr.get("key", "")
        val = attr.get("value", {})
        # Extract scalar value based on OTel data type tag
        if "stringValue" in val:
            result[key] = str(val["stringValue"])
        elif "intValue" in val:
            result[key] = str(val["intValue"])
        elif "doubleValue" in val:
            result[key] = str(val["doubleValue"])
    return result


def _parse_timestamp_nano(nano_str: str | int) -> datetime:
    """
    Helper function to convert OpenTelemetry nanosecond timestamp strings to UTC datetime.

    OTel metrics use nanoseconds since Unix epoch (`timeUnixNano`).

    Args:
        nano_str: Nanoseconds as a string or integer (e.g. '1727789832000000000').

    Returns:
        Timezone-aware UTC datetime object.
    """
    nanos = int(nano_str)
    seconds = nanos / 1_000_000_000.0  # Convert nanoseconds to float seconds
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


class OtelLikeAdapter:
    """
    Adapter implementation for OpenTelemetry-style JSON metrics.

    Implements the `TelemetryAdapter` protocol. This adapter is completely stateless
    and transforms incoming raw dicts into canonical `TelemetryRecord` objects.
    """

    @property
    def provider(self) -> str:
        """Returns the logical provider identifier ('otel')."""
        return _PROVIDER

    @property
    def integration_id(self) -> str:
        """Returns the specific adapter instance identifier ('otel-json-v1')."""
        return _INTEGRATION_ID

    def normalize(self, raw: dict[str, Any]) -> TelemetryRecord:
        """
        Main entrypoint to normalize raw OTel JSON payloads into a canonical TelemetryRecord.

        Checks the payload structure and dispatches to the appropriate format parser.

        Args:
            raw: Raw input dictionary parsed from incoming JSON.

        Returns:
            Normalized canonical TelemetryRecord object.

        Raises:
            ValueError: If the raw payload does not match any recognized OTel format.
        """
        # Format 1: Full OpenTelemetry resourceMetrics schema
        if "resourceMetrics" in raw:
            return self._parse_full_otel(raw)

        # Format 2: Simplified single-metric shorthand schema
        elif "metric" in raw and "resource" in raw:
            return self._parse_simple_shorthand(raw)

        # Unrecognized format -> fail fast
        else:
            raise ValueError(
                f"OtelLikeAdapter: unrecognised payload shape. "
                f"Expected 'resourceMetrics' or ('metric' + 'resource'). "
                f"Got keys: {list(raw.keys())}"
            )

    def _parse_simple_shorthand(self, raw: dict[str, Any]) -> TelemetryRecord:
        """
        Parse the simplified single-metric shorthand dictionary.

        Maps:
        - `resource['service.name']` -> `ResourceIdentity.service_name`
        - `resource['deployment.environment']` -> `ResourceIdentity.environment`
        - `metric['name']` -> `MetricObservation.name`
        - `metric['value']` -> `MetricObservation.value`

        Args:
            raw: Shorthand dictionary payload.

        Returns:
            Canonical TelemetryRecord object.
        """
        resource_raw: dict[str, Any] = raw.get("resource", {})
        metric_raw: dict[str, Any] = raw.get("metric", {})

        # Extract resource identification fields
        service_name = resource_raw.get("service.name", "unknown")
        environment = resource_raw.get("deployment.environment")
        namespace = resource_raw.get("service.namespace")
        version = resource_raw.get("service.version")
        host = resource_raw.get("host.name")

        # Parse timestamp (or default to current UTC time if omitted)
        ts_raw = raw.get("timestamp")
        if ts_raw:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        else:
            ts = datetime.now(tz=timezone.utc)

        # Build canonical resource identity object
        resource = ResourceIdentity(
            service_name=service_name,
            service_namespace=namespace,
            service_version=version,
            environment=environment,
            host_name=host,
        )

        # Build canonical metric observation object
        metric = MetricObservation(
            name=metric_raw["name"],
            value=float(metric_raw["value"]),
            unit=metric_raw.get("unit"),
            dimensions=metric_raw.get("dimensions", {}),
        )

        # Construct top-level canonical TelemetryRecord
        return TelemetryRecord(
            event_id=raw.get("event_id", str(uuid.uuid4())),
            timestamp=ts,
            signal_type=SignalType.METRIC,
            source=TelemetrySource(
                provider=self.provider,
                integration_id=self.integration_id,
            ),
            resource=resource,
            metric=metric,
            trace_id=raw.get("trace_id"),
            span_id=raw.get("span_id"),
            attributes=raw.get("attributes", {}),
            raw_payload=raw,  # Retain unmodified raw payload for auditing
        )

    def _parse_full_otel(self, raw: dict[str, Any]) -> TelemetryRecord:
        """
        Parse the full OpenTelemetry `resourceMetrics` schema payload.

        Navigates: `resourceMetrics[0]` -> `scopeMetrics[0]` -> `metrics[0]` -> `dataPoints[0]`

        Args:
            raw: Full OTel JSON dictionary payload.

        Returns:
            Canonical TelemetryRecord object.

        Raises:
            ValueError: If required OTel sub-lists (resourceMetrics, scopeMetrics, metrics, dataPoints) are missing/empty.
        """
        # Validate resourceMetrics array
        resource_metrics = raw.get("resourceMetrics", [])
        if not resource_metrics:
            raise ValueError("OtelLikeAdapter: resourceMetrics is empty.")

        # Extract top-level resource metadata
        rm = resource_metrics[0]
        resource_attrs_raw = rm.get("resource", {}).get("attributes", [])
        resource_attrs = _parse_otel_attributes(resource_attrs_raw)

        # Map standard OTel attributes to canonical resource identity fields
        service_name = resource_attrs.get("service.name", "unknown")
        environment = resource_attrs.get("deployment.environment")
        namespace = resource_attrs.get("service.namespace")
        version = resource_attrs.get("service.version")

        # Gather remaining custom resource attributes
        custom_attrs = {
            k: v
            for k, v in resource_attrs.items()
            if k
            not in {
                "service.name",
                "service.namespace",
                "service.version",
                "deployment.environment",
            }
        }

        resource = ResourceIdentity(
            service_name=service_name,
            service_namespace=namespace,
            service_version=version,
            environment=environment,
            attributes=custom_attrs,
        )

        # Validate scopeMetrics array
        scope_metrics = rm.get("scopeMetrics", [])
        if not scope_metrics:
            raise ValueError("OtelLikeAdapter: scopeMetrics is empty.")

        # Validate metrics array
        metrics_list = scope_metrics[0].get("metrics", [])
        if not metrics_list:
            raise ValueError("OtelLikeAdapter: metrics list is empty.")

        # Extract metric name and unit
        m = metrics_list[0]
        metric_name: str = m["name"]
        unit: str | None = m.get("unit")

        # Extract metric data points from gauge or sum signal types
        data_points: list[dict[str, Any]] = []
        if "gauge" in m:
            data_points = m["gauge"].get("dataPoints", [])
        elif "sum" in m:
            data_points = m["sum"].get("dataPoints", [])

        if not data_points:
            raise ValueError(
                f"OtelLikeAdapter: no dataPoints found for metric '{metric_name}'."
            )

        # Extract primary data point and value
        dp = data_points[0]
        value = float(dp.get("asDouble", dp.get("asInt", 0)))
        dp_attrs = _parse_otel_attributes(dp.get("attributes", []))

        # Parse timestamp from timeUnixNano or fallback to now
        ts_nano = dp.get("timeUnixNano")
        if ts_nano:
            ts = _parse_timestamp_nano(ts_nano)
        else:
            ts = datetime.now(tz=timezone.utc)

        # Build canonical MetricObservation
        metric = MetricObservation(
            name=metric_name,
            value=value,
            unit=unit,
            dimensions=dp_attrs,
        )

        # Assemble canonical TelemetryRecord
        return TelemetryRecord(
            event_id=str(uuid.uuid4()),
            timestamp=ts,
            signal_type=SignalType.METRIC,
            source=TelemetrySource(
                provider=self.provider,
                integration_id=self.integration_id,
            ),
            resource=resource,
            metric=metric,
            raw_payload=raw,
        )
