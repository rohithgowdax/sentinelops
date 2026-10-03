"""
conftest.py — shared pytest fixtures for all test layers.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import pytest

# Ensure the src directory is on the path when running tests directly
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Set minimal environment variables so Settings() doesn't fail
os.environ.setdefault("SENTINELOPS_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault(
    "SENTINELOPS_POSTGRES_DSN",
    "postgresql+asyncpg://sentinelops:sentinelops@localhost:5432/sentinelops",
)
os.environ.setdefault("SENTINELOPS_DETECTION_RULES_PATH", "config/detection_rules.yaml")


@pytest.fixture
def otel_metric_payload() -> dict[str, Any]:
    """Minimal valid OTel-like metric payload."""
    return {
        "resource": {
            "service.name": "test-service",
            "deployment.environment": "production",
            "service.namespace": "platform",
        },
        "metric": {
            "name": "http.error_rate",
            "value": 0.18,
            "unit": "ratio",
        },
        "timestamp": "2026-10-01T14:37:12Z",
    }


@pytest.fixture
def custom_metric_payload() -> dict[str, Any]:
    """Semantically equivalent custom JSON payload."""
    return {
        "svc": "test-service",
        "env": "production",
        "ns": "platform",
        "metric_name": "err_pct",
        "metric_value": 18.0,
        "unit": "percent",
        "time": "2026-10-01T14:37:12Z",
        "tags": {},
    }
