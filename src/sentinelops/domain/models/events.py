"""
Domain events.

Typed envelopes published to the EventBus. Every event has a stable
event_id so consumers can implement idempotent handling.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from sentinelops.domain.models.telemetry import TelemetryRecord
from sentinelops.domain.models.incident import Incident


class EventType(str, Enum):
    TELEMETRY_RECEIVED = "telemetry.received"
    INCIDENT_CREATED = "incident.created"
    INCIDENT_UPDATED = "incident.updated"


class DomainEvent(BaseModel):
    """Base envelope for all domain events published to the EventBus."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = "1.0"
    payload: dict[str, Any]


class TelemetryReceivedEvent(BaseModel):
    """Published to ``sentinel:telemetry`` when a canonical record is produced."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = EventType.TELEMETRY_RECEIVED
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = "1.0"
    telemetry: TelemetryRecord


class IncidentCreatedEvent(BaseModel):
    """Published to ``sentinel:incidents`` when a new incident episode is detected."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = EventType.INCIDENT_CREATED
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = "1.0"
    incident: Incident

