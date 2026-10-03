"""
Unit tests for Adapter A (`OtelLikeAdapter`).

Verifies:
- Parsing of simplified shorthand OTel JSON payloads.
- Parsing of full OpenTelemetry `resourceMetrics` JSON envelopes.
- Conversion of nanosecond timestamps (`timeUnixNano`) to UTC datetimes.
- Proper raising of `ValueError` on malformed or empty payloads.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from sentinelops.domain.models.telemetry import SignalType
from sentinelops.integrations.telemetry.otel_like.adapter import OtelLikeAdapter


@pytest.fixture
def adapter() -> OtelLikeAdapter:
    """Fixture returning an instance of OtelLikeAdapter."""
    return OtelLikeAdapter()


@pytest.fixture
def full_otel_payload() -> dict[str, Any]:
    """Fixture building a full OpenTelemetry resourceMetrics schema dictionary."""
    ts_nano = str(
        int(datetime(2026, 10, 1, 14, 37, 12, tzinfo=timezone.utc).timestamp() * 1e9)
    )
    return {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": "payments-service"},
                        },
                        {
                            "key": "service.namespace",
                            "value": {"stringValue": "commerce"},
                        },
                        {
                            "key": "deployment.environment",
                            "value": {"stringValue": "production"},
                        },
                    ]
                },
                "scopeMetrics": [
                    {
                        "metrics": [
                            {
                                "name": "http.error_rate",
                                "unit": "ratio",
                                "gauge": {
                                    "dataPoints": [
                                        {
                                            "timeUnixNano": ts_nano,
                                            "asDouble": 0.18,
                                            "attributes": [],
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                ],
            }
        ]
    }


class TestOtelLikeAdapterSimpleShorthand:
    """Tests for parsing simplified single-metric shorthand dictionaries."""

    def test_normalizes_service_name(
        self, adapter: OtelLikeAdapter, otel_metric_payload: dict[str, Any]
    ) -> None:
        """Verify service.name extracts to ResourceIdentity.service_name."""
        record = adapter.normalize(otel_metric_payload)
        assert record.resource.service_name == "test-service"

    def test_normalizes_metric_name(
        self, adapter: OtelLikeAdapter, otel_metric_payload: dict[str, Any]
    ) -> None:
        """Verify metric name extracts to MetricObservation.name."""
        record = adapter.normalize(otel_metric_payload)
        assert record.metric is not None
        assert record.metric.name == "http.error_rate"

    def test_normalizes_metric_value(
        self, adapter: OtelLikeAdapter, otel_metric_payload: dict[str, Any]
    ) -> None:
        """Verify numeric value extracts correctly."""
        record = adapter.normalize(otel_metric_payload)
        assert record.metric is not None
        assert record.metric.value == pytest.approx(0.18)

    def test_normalizes_environment(
        self, adapter: OtelLikeAdapter, otel_metric_payload: dict[str, Any]
    ) -> None:
        """Verify environment extracts to ResourceIdentity.environment."""
        record = adapter.normalize(otel_metric_payload)
        assert record.resource.environment == "production"

    def test_signal_type_is_metric(
        self, adapter: OtelLikeAdapter, otel_metric_payload: dict[str, Any]
    ) -> None:
        """Verify signal_type is set to SignalType.METRIC."""
        record = adapter.normalize(otel_metric_payload)
        assert record.signal_type == SignalType.METRIC

    def test_provider_is_otel(
        self, adapter: OtelLikeAdapter, otel_metric_payload: dict[str, Any]
    ) -> None:
        """Verify source provider tag is 'otel'."""
        record = adapter.normalize(otel_metric_payload)
        assert record.source.provider == "otel"

    def test_raw_payload_preserved(
        self, adapter: OtelLikeAdapter, otel_metric_payload: dict[str, Any]
    ) -> None:
        """Verify original input dictionary is preserved in raw_payload."""
        record = adapter.normalize(otel_metric_payload)
        assert record.raw_payload == otel_metric_payload

    def test_timestamp_parsed(
        self, adapter: OtelLikeAdapter, otel_metric_payload: dict[str, Any]
    ) -> None:
        """Verify timestamp string is parsed to UTC datetime."""
        record = adapter.normalize(otel_metric_payload)
        assert record.timestamp.year == 2026
        assert record.timestamp.month == 10

    def test_unknown_format_raises(self, adapter: OtelLikeAdapter) -> None:
        """Verify that unrecognizable payload structure raises ValueError."""
        with pytest.raises(ValueError, match="unrecognised"):
            adapter.normalize({"random_field": 42})


class TestOtelLikeAdapterFullEnvelope:
    """Tests for parsing full OpenTelemetry resourceMetrics JSON schema."""

    def test_full_envelope_service_name(
        self, adapter: OtelLikeAdapter, full_otel_payload: dict[str, Any]
    ) -> None:
        """Verify service name extraction from OTel resource attributes array."""
        record = adapter.normalize(full_otel_payload)
        assert record.resource.service_name == "payments-service"

    def test_full_envelope_metric_value(
        self, adapter: OtelLikeAdapter, full_otel_payload: dict[str, Any]
    ) -> None:
        """Verify numeric value extraction from OTel gauge dataPoints array."""
        record = adapter.normalize(full_otel_payload)
        assert record.metric is not None
        assert record.metric.value == pytest.approx(0.18)

    def test_full_envelope_namespace(
        self, adapter: OtelLikeAdapter, full_otel_payload: dict[str, Any]
    ) -> None:
        """Verify service namespace extraction."""
        record = adapter.normalize(full_otel_payload)
        assert record.resource.service_namespace == "commerce"

    def test_empty_resource_metrics_raises(self, adapter: OtelLikeAdapter) -> None:
        """Verify that empty resourceMetrics array raises ValueError."""
        with pytest.raises(ValueError):
            adapter.normalize({"resourceMetrics": []})
