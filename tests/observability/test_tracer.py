"""
Unit Tests for OpenTelemetry Tracer, Span Context, and Sensitive Attribute Redaction.
"""
from __future__ import annotations

import pytest

from sentinelops.observability.tracer import (
    SpanStatus,
    Tracer,
    generate_span_id,
    generate_trace_id,
    sanitize_attributes,
)


class TestObservabilityTracer:
    def test_trace_and_span_id_formats(self) -> None:
        t_id = generate_trace_id()
        s_id = generate_span_id()
        assert len(t_id) == 32  # 128-bit W3C format
        assert len(s_id) == 16  # 64-bit W3C format
        assert int(t_id, 16) > 0
        assert int(s_id, 16) > 0

    def test_sensitive_attributes_are_automatically_redacted(self) -> None:
        raw = {
            "service.name": "payments-service",
            "db.password": "super-secret-123",
            "api_key": "sk-proj-abc",
            "auth_token": "bearer-xyz",
            "chain_of_thought": "hidden thoughts",
            "scratchpad": "reasoning steps",
            "raw_cot": "internal tokens",
            "aws_header": "Header contains AKIAIOSFODNN7EXAMPLE key",
            "nested": {
                "user_token": "secret-nested",
                "normal_val": 42,
            },
        }
        sanitized = sanitize_attributes(raw)
        assert sanitized["service.name"] == "payments-service"
        assert sanitized["db.password"] == "[REDACTED_SECRET]"
        assert sanitized["api_key"] == "[REDACTED_SECRET]"
        assert sanitized["auth_token"] == "[REDACTED_SECRET]"
        assert sanitized["chain_of_thought"] == "[REDACTED_THOUGHT]"
        assert sanitized["scratchpad"] == "[REDACTED_THOUGHT]"
        assert sanitized["raw_cot"] == "[REDACTED_THOUGHT]"
        assert "[REDACTED_SECRET]" in sanitized["aws_header"]
        assert "AKIAIOSFODNN7EXAMPLE" not in sanitized["aws_header"]
        assert sanitized["nested"]["user_token"] == "[REDACTED_SECRET]"
        assert sanitized["nested"]["normal_val"] == 42

    def test_tracer_span_lifecycle_and_duration(self) -> None:
        tracer = Tracer(service_name="test-sentinel", environment="staging")
        with tracer.span("test_operation", attributes={"incident_id": "INC-01"}) as span:
            span.set_attribute("gen_ai.request.model", "gpt-4o-mini")
            span.add_event("step_completed", {"step": 1})

        assert span.name == "test_operation"
        assert span.status == SpanStatus.OK
        assert span.duration_seconds >= 0.0
        assert span.attributes["incident_id"] == "INC-01"
        assert span.attributes["service.name"] == "test-sentinel"
        assert span.attributes["deployment.environment"] == "staging"
        assert len(span.events) == 1
        assert span.events[0].name == "step_completed"

    def test_tracer_records_error_status_on_exception(self) -> None:
        tracer = Tracer()
        with pytest.raises(ValueError):
            with tracer.span("failing_node") as span:
                raise ValueError("Simulated node failure")

        assert span.status == SpanStatus.ERROR
        assert "Simulated node failure" in span.status_message
        assert span.attributes["error.type"] == "ValueError"

    @pytest.mark.asyncio
    async def test_tracer_async_context_manager(self) -> None:
        tracer = Tracer()
        async with tracer.async_span("async_step", attributes={"step": "collect"}) as s:
            s.set_attribute("tool.name", "query_metrics")

        assert s.status == SpanStatus.OK
        assert s.attributes["tool.name"] == "query_metrics"
