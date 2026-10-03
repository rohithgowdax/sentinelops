"""
Canonical incident domain models for SentinelOps.

An Incident is a first-class domain object representing an active operational failure.
Incidents are created deterministically by the Detection Engine when a rule threshold is violated.

Architectural Rule:
- Incidents are NEVER created directly by LLMs.
- Incidents are created by rule evaluation and published to the EventBus.
- Agents (LangGraph/LLM) only read, investigate, and annotate incidents.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class IncidentSeverity(str, Enum):
    """
    Severity levels for incidents.

    Attributes:
        LOW: Minor operational deviation (e.g. slight latency increase).
        MEDIUM: Degraded performance affecting non-critical paths.
        HIGH: Significant failure affecting core services or SLA thresholds.
        CRITICAL: Major outage or severe SLA breach requiring immediate intervention.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, Enum):
    """
    Lifecycle status of an incident.

    Attributes:
        OPEN: Newly detected incident awaiting investigation.
        INVESTIGATING: Agent or SRE actively diagnosing root cause.
        RESOLVED: Remediation verified and operational metrics returned to normal.
        CLOSED: Incident investigation lifecycle finished and archived.
    """

    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TriggerType(str, Enum):
    """
    Mechanism that triggered the incident creation.

    Attributes:
        METRIC_THRESHOLD: Deterministic metric rule evaluation (gt/lt threshold).
        LOG_PATTERN: Log error rate or exception pattern match.
        ANOMALY: Statistical or ML anomaly detector (future slice).
        EXTERNAL: Inbound webhook or manual user trigger.
    """

    METRIC_THRESHOLD = "metric_threshold"
    LOG_PATTERN = "log_pattern"
    ANOMALY = "anomaly"
    EXTERNAL = "external"


class EvidenceItem(BaseModel):
    """
    Represents a specific piece of evidence attached to an incident at detection time.

    Fields:
        evidence_id: Unique identifier for this evidence item.
        kind: Category of telemetry evidence ('metric', 'log', 'event').
        description: Human-readable explanation of what was observed.
        value: Numeric or structural value observed (e.g. 0.18 for 18% error rate).
        telemetry_event_id: Pointer back to the canonical TelemetryRecord event_id.
        timestamp: Time when this evidence point was recorded.
        attributes: Additional key-value context metadata (rule_id, threshold, etc.).
    """

    evidence_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this evidence item.",
    )
    kind: str = Field(
        description="Type of evidence, e.g. 'metric', 'log', 'event'."
    )
    description: str = Field(
        description="Detailed description of the observed evidence."
    )
    value: Any | None = Field(
        default=None, description="Observed numeric or scalar value."
    )
    telemetry_event_id: str | None = Field(
        default=None,
        description="ID of the triggering TelemetryRecord for auditability.",
    )
    timestamp: datetime | None = Field(
        default=None, description="Timestamp when evidence was observed."
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Rule details, threshold parameters, and evaluation metadata.",
    )


class Incident(BaseModel):
    """
    Canonical representation of an incident in SentinelOps.

    This model is provider-neutral and contains all information required by SREs
    and AI agents to perform investigation and remediation.

    Fields:
        incident_id: Unique formatted ID (e.g. 'INC-A1B2C3D4').
        created_at: Time when the incident was detected and created (UTC).
        updated_at: Time of last status update or evidence attachment (UTC).
        severity: Criticality rating (LOW, MEDIUM, HIGH, CRITICAL).
        status: Lifecycle state (OPEN, INVESTIGATING, RESOLVED, CLOSED).
        service_name: Name of the impacted microservice.
        service_namespace: Namespace or domain of the impacted service.
        environment: Target environment ('production', 'staging').
        trigger_type: Detection mechanism category (e.g. METRIC_THRESHOLD).
        trigger_rule_id: ID of the detection rule that fired.
        trigger_rule_name: Human-readable name of the firing rule.
        initial_evidence: List of telemetry evidence collected during detection.
        title: Generated title summarizing the failure condition.
        description: Generated summary description of the incident trigger.
        source_provider: Source context identifier ('sentinelops-detector').
        source_integration_id: Integration context identifier.
        episode_key: Unique composite key ('rule_id::service::env') used to deduplicate active incidents.
        context: Arbitrary diagnostic dictionary.
    """

    # Formatted Incident ID (e.g. INC-E4A3B2C1)
    incident_id: str = Field(
        default_factory=lambda: f"INC-{str(uuid.uuid4())[:8].upper()}",
        description="Formatted unique incident identifier.",
    )
    created_at: datetime = Field(
        description="UTC timestamp when the incident was detected."
    )
    updated_at: datetime = Field(
        description="UTC timestamp when the incident was last modified."
    )

    # Classification and lifecycle status
    severity: IncidentSeverity = Field(
        description="Severity level of the incident."
    )
    status: IncidentStatus = Field(
        default=IncidentStatus.OPEN,
        description="Current status of the incident (default: OPEN).",
    )

    # Impacted service details
    service_name: str = Field(
        description="Name of the affected service (e.g. 'payments-service')."
    )
    service_namespace: str | None = Field(
        default=None, description="Namespace or team owning the service."
    )
    environment: str | None = Field(
        default=None, description="Target environment, e.g. 'production'."
    )

    # Rule trigger metadata
    trigger_type: TriggerType = Field(
        description="Detection mechanism that triggered this incident."
    )
    trigger_rule_id: str | None = Field(
        default=None, description="ID of the rule that evaluated to true."
    )
    trigger_rule_name: str | None = Field(
        default=None, description="Human-readable rule name."
    )

    # Telemetry evidence attached at detection
    initial_evidence: list[EvidenceItem] = Field(
        default_factory=list,
        description="Initial telemetry evidence captured during rule evaluation.",
    )

    # Generated incident text
    title: str = Field(
        description="Deterministic incident title."
    )
    description: str = Field(
        description="Detailed deterministic description of the incident context."
    )

    # Integration origins
    source_provider: str = Field(
        description="System that generated the incident ('sentinelops-detector')."
    )
    source_integration_id: str = Field(
        description="Integration identifier associated with the trigger."
    )

    # Key used for deduplicating active incidents across detection runs
    episode_key: str = Field(
        description="Stable composite key ('rule_id::service::env') to prevent duplicate incidents for ongoing outages."
    )

    # Additional diagnostic context dictionary
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra context data (e.g. observed values, sample counts, thresholds).",
    )

    model_config = {"frozen": False}
