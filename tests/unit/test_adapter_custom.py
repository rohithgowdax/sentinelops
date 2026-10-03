"""
Unit tests for Adapter B (`CustomJsonAdapter`).

Verifies:
- Extraction of non-standard vendor field names (`svc` -> `service_name`, `env` -> `environment`, `tags` -> `dimensions`).
- Metric name normalization (`err_pct` -> `http.error_rate`).
- Unit scaling (converting percentage values 0..100 to ratio 0..1).
- Error handling for missing required fields or non-numeric values.
"""
from __future__ import annotations

from typing import Any

import pytest

from sentinelops.domain.models.telemetry import SignalType
from sentinelops.integrations.telemetry.custom_json.adapter import CustomJsonAdapter


@pytest.fixture
def adapter() -> CustomJsonAdapter:
    """Fixture returning an instance of CustomJsonAdapter."""
    return CustomJsonAdapter()


class TestCustomJsonAdapter:
    """Test suite covering CustomJsonAdapter normalizations."""

    def test_normalizes_service_name(
        self, adapter: CustomJsonAdapter, custom_metric_payload: dict[str, Any]
    ) -> None:
        """Verify 'svc' field maps to ResourceIdentity.service_name."""
        record = adapter.normalize(custom_metric_payload)
        assert record.resource.service_name == "test-service"

    def test_maps_err_pct_to_canonical_name(
        self, adapter: CustomJsonAdapter, custom_metric_payload: dict[str, Any]
    ) -> None:
        """Verify metric name mapping: 'err_pct' -> 'http.error_rate'."""
        record = adapter.normalize(custom_metric_payload)
        assert record.metric is not None
        assert record.metric.name == "http.error_rate"

    def test_normalizes_percent_to_ratio(
        self, adapter: CustomJsonAdapter, custom_metric_payload: dict[str, Any]
    ) -> None:
        """Verify percentage unit scaling: 18.0 percent -> 0.18 ratio."""
        record = adapter.normalize(custom_metric_payload)
        assert record.metric is not None
        assert record.metric.value == pytest.approx(0.18)
        assert record.metric.unit == "ratio"

    def test_normalizes_environment(
        self, adapter: CustomJsonAdapter, custom_metric_payload: dict[str, Any]
    ) -> None:
        """Verify 'env' field maps to ResourceIdentity.environment."""
        record = adapter.normalize(custom_metric_payload)
        assert record.resource.environment == "production"

    def test_signal_type_is_metric(
        self, adapter: CustomJsonAdapter, custom_metric_payload: dict[str, Any]
    ) -> None:
        """Verify signal_type is set to SignalType.METRIC."""
        record = adapter.normalize(custom_metric_payload)
        assert record.signal_type == SignalType.METRIC

    def test_provider_is_custom_json(
        self, adapter: CustomJsonAdapter, custom_metric_payload: dict[str, Any]
    ) -> None:
        """Verify source provider tag is 'custom_json'."""
        record = adapter.normalize(custom_metric_payload)
        assert record.source.provider == "custom_json"

    def test_raw_payload_preserved(
        self, adapter: CustomJsonAdapter, custom_metric_payload: dict[str, Any]
    ) -> None:
        """Verify input dictionary is preserved in raw_payload."""
        record = adapter.normalize(custom_metric_payload)
        assert record.raw_payload == custom_metric_payload

    def test_timestamp_parsed(
        self, adapter: CustomJsonAdapter, custom_metric_payload: dict[str, Any]
    ) -> None:
        """Verify ISO 8601 'time' string parses to datetime."""
        record = adapter.normalize(custom_metric_payload)
        assert record.timestamp.year == 2026

    def test_missing_required_fields_raises(self, adapter: CustomJsonAdapter) -> None:
        """Verify that omitting required fields ('svc', 'metric_name', 'metric_value') raises ValueError."""
        with pytest.raises(ValueError, match="missing required fields"):
            adapter.normalize({"svc": "payments"})  # missing metric_name and metric_value

    def test_tags_become_dimensions(self, adapter: CustomJsonAdapter) -> None:
        """Verify 'tags' key-value dictionary converts to MetricObservation.dimensions."""
        payload = {
            "svc": "auth-service",
            "metric_name": "err_pct",
            "metric_value": 5.0,
            "unit": "percent",
            "tags": {"region": "us-east-1", "az": "us-east-1a"},
        }
        record = adapter.normalize(payload)
        assert record.metric is not None
        assert record.metric.dimensions.get("region") == "us-east-1"

    def test_non_percent_value_not_scaled(self, adapter: CustomJsonAdapter) -> None:
        """Verify values with units other than percent (e.g. 'ms') are NOT scaled down."""
        payload = {
            "svc": "order-service",
            "metric_name": "lat_p99_ms",
            "metric_value": 350.0,
            "unit": "ms",
        }
        record = adapter.normalize(payload)
        assert record.metric is not None
        assert record.metric.value == pytest.approx(350.0)
        assert record.metric.name == "http.latency.p99"

    def test_numeric_string_metric_value_raises(
        self, adapter: CustomJsonAdapter
    ) -> None:
        """Verify non-numeric metric_value strings raise ValueError."""
        with pytest.raises(ValueError, match="metric_value must be numeric"):
            adapter.normalize({
                "svc": "svc",
                "metric_name": "err_pct",
                "metric_value": "not-a-number",
            })

    def test_unknown_metric_name_passes_through(
        self, adapter: CustomJsonAdapter
    ) -> None:
        """Verify unmapped metric names pass through unchanged."""
        payload = {
            "svc": "svc",
            "metric_name": "custom.my_metric",
            "metric_value": 42.0,
        }
        record = adapter.normalize(payload)
        assert record.metric is not None
        assert record.metric.name == "custom.my_metric"
