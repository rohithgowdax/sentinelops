"""
OpenTelemetry Semantic Tracer and Span Management for SentinelOps.

Follows OpenTelemetry Semantic Conventions for:
- Trace context propagation (W3C TraceContext: trace_id, span_id, parent_span_id)
- Agent and GenAI operations (gen_ai.system, gen_ai.request.model, gen_ai.usage.*)
- Tool, Retrieval, Policy, and Infrastructure operations
- Automatic redaction of secrets, credentials, and raw chain-of-thought
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Iterator
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Patterns for secret redaction
SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|token|secret|authorization|api_key|private_key|credentials|cookie|bearer|thought)",
    re.IGNORECASE,
)


def generate_trace_id() -> str:
    """Generate 128-bit W3C TraceContext trace ID (32 hex chars)."""
    return secrets.token_hex(16)


def generate_span_id() -> str:
    """Generate 64-bit W3C TraceContext span ID (16 hex chars)."""
    return secrets.token_hex(8)


def sanitize_attributes(attrs: dict[str, Any]) -> dict[str, Any]:
    """Recursively scrub sensitive keys and protect privacy in telemetry."""
    sanitized: dict[str, Any] = {}
    for k, v in attrs.items():
        if SENSITIVE_KEY_PATTERN.search(k):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, dict):
            sanitized[k] = sanitize_attributes(v)
        elif isinstance(v, (str, int, float, bool)) or v is None:
            sanitized[k] = v
        else:
            sanitized[k] = str(v)
    return sanitized


class SpanStatus(str, Enum):
    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"


class SpanEvent(BaseModel):
    name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    attributes: dict[str, Any] = Field(default_factory=dict)


class Span(BaseModel):
    """OpenTelemetry-compliant Span record."""

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    start_time: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    end_time: datetime | None = None
    status: SpanStatus = SpanStatus.UNSET
    status_message: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[SpanEvent] = Field(default_factory=list)

    def set_attribute(self, key: str, value: Any) -> Span:
        if SENSITIVE_KEY_PATTERN.search(key):
            self.attributes[key] = "[REDACTED]"
        else:
            self.attributes[key] = value
        return self

    def set_attributes(self, attrs: dict[str, Any]) -> Span:
        for k, v in attrs.items():
            self.set_attribute(k, v)
        return self

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> Span:
        sanitized = sanitize_attributes(attributes or {})
        self.events.append(SpanEvent(name=name, attributes=sanitized))
        return self

    def end(self, status: SpanStatus = SpanStatus.OK, message: str | None = None) -> None:
        if self.end_time is None:
            self.end_time = datetime.now(tz=timezone.utc)
        if self.status == SpanStatus.UNSET:
            self.status = status
        if message:
            self.status_message = message

    @property
    def duration_seconds(self) -> float:
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0


class Tracer:
    """In-process OpenTelemetry-compatible Tracer."""

    def __init__(self, service_name: str = "sentinelops-core", environment: str = "production") -> None:
        self.service_name = service_name
        self.environment = environment
        self._spans: list[Span] = []

    def start_span(
        self,
        name: str,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        t_id = trace_id or generate_trace_id()
        s_id = generate_span_id()
        base_attrs = {
            "service.name": self.service_name,
            "deployment.environment": self.environment,
            "telemetry.sdk.name": "sentinelops-otel",
            "telemetry.sdk.version": "1.0.0",
        }
        if attributes:
            base_attrs.update(sanitize_attributes(attributes))

        span = Span(
            name=name,
            trace_id=t_id,
            span_id=s_id,
            parent_span_id=parent_span_id,
            attributes=base_attrs,
        )
        self._spans.append(span)
        return span

    @contextmanager
    def span(
        self,
        name: str,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[Span]:
        s = self.start_span(name, trace_id, parent_span_id, attributes)
        try:
            yield s
            s.end(SpanStatus.OK)
        except Exception as exc:
            s.end(SpanStatus.ERROR, str(exc))
            s.set_attribute("error.type", type(exc).__name__)
            raise

    @asynccontextmanager
    async def async_span(
        self,
        name: str,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> AsyncIterator[Span]:
        s = self.start_span(name, trace_id, parent_span_id, attributes)
        try:
            yield s
            s.end(SpanStatus.OK)
        except Exception as exc:
            s.end(SpanStatus.ERROR, str(exc))
            s.set_attribute("error.type", type(exc).__name__)
            raise

    def get_spans(self, trace_id: str | None = None) -> list[Span]:
        if trace_id:
            return [s for s in self._spans if s.trace_id == trace_id]
        return list(self._spans)

    def clear(self) -> None:
        self._spans.clear()


# Global default tracer
_default_tracer = Tracer()


def get_tracer(service_name: str = "sentinelops-core") -> Tracer:
    global _default_tracer
    if _default_tracer.service_name != service_name:
        _default_tracer = Tracer(service_name=service_name)
    return _default_tracer
