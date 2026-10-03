"""
Canonical telemetry domain models for SentinelOps.

These Pydantic models represent the provider-neutral internal schema of all
telemetry signals processed by SentinelOps.

Key Design Principles:
1. Vendor Neutrality: No OpenTelemetry, Datadog, or Prometheus specific names exist here.
2. Normalized Payload: External data is parsed into `MetricObservation` or `LogRecord`.
3. Lossless Traceability: The original payload is preserved in `raw_payload` for auditability.
4. Core Pipeline Decoupling: Ingestion, Storage, and Detection Engine only consume these models.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SignalType(str, Enum):
    """
    Enum representing the supported telemetry signal classes.
    
    Attributes:
        METRIC: Numerical metrics (e.g. error rate, CPU usage, latency).
        LOG: Structured or unstructured textual log records.
        TRACE: Distributed tracing span data.
        EVENT: Discrete operational events (e.g. deployments, restarts).
    """

    METRIC = "metric"
    LOG = "log"
    TRACE = "trace"
    EVENT = "event"


class Severity(str, Enum):
    """
    Normalized severity / log level across all providers.
    
    Mapped by adapters from vendor log levels (e.g. WARN -> WARNING, FATAL -> CRITICAL).
    """

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class TelemetrySource(BaseModel):
    """
    Identifies the originating system and integration adapter of a telemetry signal.

    Fields:
        provider: Logical name of the source ecosystem (e.g. 'otel', 'custom_json', 'datadog').
        integration_id: Unique identifier for the specific adapter instance (e.g. 'otel-json-v1').
        raw_format_version: Optional version tag of the raw incoming payload structure.
    """

    provider: str = Field(
        description="Logical provider name, e.g. 'otel', 'custom_json', 'datadog'."
    )
    integration_id: str = Field(
        description="Unique adapter / integration identifier within the provider."
    )
    raw_format_version: str | None = Field(
        default=None,
        description="Version string of the external format, if available.",
    )


class ResourceIdentity(BaseModel):
    """
    Provider-neutral representation of the service or host emitting the telemetry.

    Fields:
        service_name: Name of the microservice or application (e.g. 'payments-service').
        service_namespace: Logical domain or cluster namespace (e.g. 'commerce').
        service_version: Semantic or git version string (e.g. 'v1.4.2').
        environment: Deployment stage (e.g. 'production', 'staging', 'development').
        host_name: Physical host or pod name emitting the telemetry.
        attributes: Free-form key-value string metadata associated with the resource.
    """

    service_name: str = Field(description="Logical service or application name.")
    service_namespace: str | None = Field(
        default=None, description="Logical namespace or team owner."
    )
    service_version: str | None = Field(
        default=None, description="Version tag of the deployed service."
    )
    environment: str | None = Field(
        default=None,
        description="Deployment environment, e.g. 'production', 'staging'.",
    )
    host_name: str | None = Field(
        default=None, description="Host server or pod identifier."
    )
    # Additional key-value pairs associated with this resource
    attributes: dict[str, str] = Field(
        default_factory=dict, description="Custom metadata attributes."
    )


class MetricObservation(BaseModel):
    """
    Canonical representation of a single numeric metric sample.

    All incoming metrics (whether from Prometheus, OpenTelemetry, or Custom JSON)
    are transformed into this standardized representation.

    Fields:
        name: Standardized metric name (e.g. 'http.error_rate', 'http.latency.p99').
        value: Floating-point numeric metric value.
        unit: Standardized unit of measurement (e.g. 'ratio', 'ms', 'bytes').
        dimensions: Label/tag metadata (e.g. {'method': 'POST', 'status_code': '500'}).
    """

    name: str = Field(description="Canonical metric name, e.g. 'http.error_rate'.")
    value: float = Field(description="Numerical value of the metric observation.")
    unit: str | None = Field(
        default=None,
        description="Unit of measure, e.g. 'percent', 'ms', 'requests', 'ratio'.",
    )
    dimensions: dict[str, str] = Field(
        default_factory=dict,
        description="Metric dimensions / labels (key-value metadata pairs).",
    )


class LogRecord(BaseModel):
    """
    Canonical representation of a log message.

    Fields:
        severity: Standardized severity level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        message: Main log text body.
        attributes: Additional contextual metadata associated with the log entry.
    """

    severity: Severity = Field(
        default=Severity.INFO, description="Log severity level."
    )
    message: str = Field(description="Text contents of the log message.")
    attributes: dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary JSON metadata."
    )


class TelemetryRecord(BaseModel):
    """
    Top-level envelope encapsulating a single canonical telemetry event.

    Every inbound data point (metric, log, trace) is normalized by an adapter into a
    `TelemetryRecord` before publication to the EventBus.

    Fields:
        event_id: UUID string serving as a globally unique idempotency key.
        timestamp: Time when the telemetry was recorded (UTC).
        signal_type: The signal category (METRIC, LOG, TRACE, EVENT).
        source: Provider metadata (where the data came from).
        resource: Resource identity (which service emitted the data).
        metric: Optional metric payload (populated if signal_type == METRIC).
        log: Optional log payload (populated if signal_type == LOG).
        trace_id: Distributed trace ID for cross-service correlation.
        span_id: Span ID for trace execution steps.
        attributes: General free-form context metadata.
        raw_payload: Unmodified external raw dictionary preserved for auditing/debugging.
    """

    # Unique event ID generated automatically if omitted (ensures idempotency across workers)
    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Globally unique event identifier (idempotency key).",
    )
    # UTC Timestamp of event occurrence
    timestamp: datetime = Field(
        description="Event timestamp in UTC."
    )
    # Category of signal (METRIC or LOG)
    signal_type: SignalType = Field(
        description="Category of telemetry signal (metric, log, trace, event)."
    )

    # Telemetry origins and target resource
    source: TelemetrySource = Field(
        description="Metadata describing the provider and adapter instance."
    )
    resource: ResourceIdentity = Field(
        description="Identity of the service or host emitting the telemetry."
    )

    # Specific payload objects (only one is active based on signal_type)
    metric: MetricObservation | None = Field(
        default=None, description="Metric payload data if signal_type is METRIC."
    )
    log: LogRecord | None = Field(
        default=None, description="Log payload data if signal_type is LOG."
    )

    # Tracing handles for distributed context correlation
    trace_id: str | None = Field(
        default=None, description="Distributed trace ID (hex string)."
    )
    span_id: str | None = Field(
        default=None, description="Distributed span ID (hex string)."
    )

    # Free-form context tags
    attributes: dict[str, Any] = Field(
        default_factory=dict, description="Additional context attributes."
    )

    # Original external payload preserved for inspection
    raw_payload: dict[str, Any] | None = Field(
        default=None,
        description="Original untransformed raw payload from the external source.",
    )

    model_config = {"frozen": False}
