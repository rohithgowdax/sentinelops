"""
Audit Trail Service for SentinelOps Controlled Remediation.

Maintains an immutable, structured audit log of all incident, policy, approval,
action execution, and verification events.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AuditEvent(BaseModel):
    """Immutable audit record representing an operational lifecycle event."""

    event_id: str = Field(default_factory=lambda: f"AUD-{uuid4().hex[:10]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    incident_id: str = Field(...)
    action_id: str | None = Field(default=None)
    actor: str = Field(default="system")
    event_type: str = Field(..., description="Canonical event identifier, e.g. 'action.proposed'")
    payload: dict[str, Any] = Field(default_factory=dict)


class AuditService:
    """In-memory or operational store backed audit trail service."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def record(
        self,
        event_type: str,
        incident_id: str,
        action_id: str | None = None,
        actor: str = "system",
        payload: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            incident_id=incident_id,
            action_id=action_id,
            actor=actor,
            event_type=event_type,
            payload=payload or {},
        )
        self._events.append(event)
        logger.info(
            "AUDIT [%s] incident=%s action=%s actor=%s",
            event_type,
            incident_id,
            action_id,
            actor,
        )
        return event

    def get_events_for_incident(self, incident_id: str) -> list[AuditEvent]:
        return [e for e in self._events if e.incident_id == incident_id]

    def get_incident_events(self, incident_id: str) -> list[AuditEvent]:
        return self.get_events_for_incident(incident_id)

    def get_events_for_action(self, action_id: str) -> list[AuditEvent]:
        return [e for e in self._events if e.action_id == action_id]

    def all_events(self) -> list[AuditEvent]:
        return list(self._events)
