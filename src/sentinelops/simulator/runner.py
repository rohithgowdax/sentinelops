"""
Real-time Production Failure Scenario Simulator for SentinelOps.

Role:
Simulates a live microservice outage scenario for `payments-service` across 3 distinct phases.
Emits telemetry concurrently through BOTH `OtelLikeAdapter` and `CustomJsonAdapter`.

Simulation Timeline (~70 seconds total):
1. Phase 1 — Healthy (0s..30s):
   - Error rate: ~1–2% (0.01..0.02 ratio).
   - Latency: ~45–60ms.
   - Result: Detection Engine remains quiet (threshold is 10%).

2. Phase 2 — Failure Onset (30s..50s):
   - Error rate spikes to 18–25% (0.18..0.25 ratio).
   - Latency spikes to 350–500ms.
   - Result: Detection Engine evaluates threshold > 0.10, creates canonical `Incident`,
     and publishes `IncidentCreatedEvent` to `sentinel:incidents`.

3. Phase 3 — Sustained Plateau (50s..70s):
   - High error rate continues (20–22%).
   - Result: Detection Engine evaluates threshold > 0.10, finds active episode key
     ('rule-001::payments-service::production') in `OperationalStore`, and DEDUPLICATES (no duplicate incident).

Generalization Proof:
In each 2-second tick, TWO raw payloads are constructed:
- OTel JSON payload -> parsed by `OtelLikeAdapter`
- Custom JSON payload -> parsed by `CustomJsonAdapter`
Both produce canonical `TelemetryRecord` objects and publish them to Redis (`sentinel:telemetry`).
"""
from __future__ import annotations

import asyncio
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from sentinelops.config.settings import get_settings
from sentinelops.domain.models.events import TelemetryReceivedEvent
from sentinelops.integrations.event_bus.redis_bus import RedisEventBus
from sentinelops.integrations.telemetry.custom_json.adapter import CustomJsonAdapter
from sentinelops.integrations.telemetry.otel_like.adapter import OtelLikeAdapter

# Initialize logger
log = structlog.get_logger(__name__)

# Constants defining the simulated microservice
_SERVICE = "payments-service"
_NAMESPACE = "commerce"
_ENVIRONMENT = "production"

# Instantiate adapter singletons (stateless normalizers)
_OTEL_ADAPTER = OtelLikeAdapter()
_CUSTOM_ADAPTER = CustomJsonAdapter()


def _otel_payload(
    error_rate: float,
    latency_p99: float,
    ts: datetime,
) -> dict[str, Any]:
    """
    Construct a raw OpenTelemetry-style metrics JSON dictionary.

    Args:
        error_rate: Error rate expressed as a float ratio (e.g. 0.18).
        latency_p99: Latency in milliseconds.
        ts: UTC datetime timestamp.

    Returns:
        Raw OTel `resourceMetrics` schema dictionary.
    """
    ts_nano = int(ts.timestamp() * 1_000_000_000)
    return {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": _SERVICE}},
                        {
                            "key": "service.namespace",
                            "value": {"stringValue": _NAMESPACE},
                        },
                        {
                            "key": "deployment.environment",
                            "value": {"stringValue": _ENVIRONMENT},
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
                                            "timeUnixNano": str(ts_nano),
                                            "asDouble": error_rate,
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


def _custom_payload(
    error_rate_pct: float,
    latency_p99: float,
    ts: datetime,
) -> dict[str, Any]:
    """
    Construct a raw custom JSON telemetry dictionary.

    Note: `err_pct` is expressed on a 0-100 percentage scale (e.g. 18.4).
    `CustomJsonAdapter` will scale this to a 0-1 ratio (0.184) to match OTel semantics.

    Args:
        error_rate_pct: Error rate percentage (0–100).
        latency_p99: Latency in milliseconds.
        ts: UTC datetime timestamp.

    Returns:
        Raw custom JSON schema dictionary.
    """
    return {
        "svc": _SERVICE,
        "env": _ENVIRONMENT,
        "ns": _NAMESPACE,
        "metric_name": "err_pct",
        "metric_value": error_rate_pct,  # e.g. 18.4 -> CustomJsonAdapter maps to 0.184
        "unit": "percent",
        "time": ts.isoformat(),
        "tags": {"region": "us-east-1"},
        "src_id": "custom-agent-001",
    }


async def run_scenario(bus: RedisEventBus) -> None:
    """
    Orchestrate the 3-phase production simulation scenario.

    Timeline:
    - 0–30s: Healthy phase
    - 30–50s: Failure onset phase
    - 50–70s: Sustained failure plateau phase

    Args:
        bus: Connected `RedisEventBus` instance.
    """
    # Ensure consumer groups are initialized in Redis
    await bus.ensure_consumer_group(bus._telemetry_stream, "sentinelops-workers")
    await bus.ensure_consumer_group(bus._incidents_stream, "sentinelops-workers")

    log.info("simulator.started", service=_SERVICE)

    # Phase tuple configuration: (phase_name, duration_sec, error_min, error_max, lat_min, lat_max)
    phases = [
        ("healthy", 30, 0.01, 0.02, 45, 60),
        ("failure_onset", 20, 0.18, 0.25, 350, 500),
        ("plateau", 20, 0.20, 0.22, 400, 480),
    ]

    for phase_name, duration_s, err_lo, err_hi, lat_lo, lat_hi in phases:
        log.info(
            "simulator.phase_start", phase=phase_name, duration_seconds=duration_s
        )
        end_time = time.time() + duration_s

        while time.time() < end_time:
            ts = datetime.now(tz=timezone.utc)
            error_rate = random.uniform(err_lo, err_hi)
            latency = random.uniform(lat_lo, lat_hi)

            # ── 1. Emit via Adapter A (OpenTelemetry) ─────────────────────────
            otel_raw = _otel_payload(
                error_rate=error_rate, latency_p99=latency, ts=ts
            )
            try:
                # Normalize raw OTel dictionary into canonical TelemetryRecord
                record_a = _OTEL_ADAPTER.normalize(otel_raw)
                event_a = TelemetryReceivedEvent(telemetry=record_a)
                # Publish event to Redis Stream 'sentinel:telemetry'
                await bus.publish_telemetry(event_a)
                log.debug(
                    "simulator.otel.emitted",
                    phase=phase_name,
                    error_rate=round(error_rate, 4),
                )
            except Exception as exc:
                log.error("simulator.otel.error", error=str(exc))

            # ── 2. Emit via Adapter B (Custom JSON) ───────────────────────────
            custom_raw = _custom_payload(
                error_rate_pct=error_rate * 100.0,  # Scale to 0-100 %
                latency_p99=latency,
                ts=ts,
            )
            try:
                # Normalize raw Custom JSON dictionary into canonical TelemetryRecord
                record_b = _CUSTOM_ADAPTER.normalize(custom_raw)
                event_b = TelemetryReceivedEvent(telemetry=record_b)
                # Publish event to Redis Stream 'sentinel:telemetry'
                await bus.publish_telemetry(event_b)
                log.debug(
                    "simulator.custom.emitted",
                    phase=phase_name,
                    err_pct=round(error_rate * 100.0, 2),
                )
            except Exception as exc:
                log.error("simulator.custom.error", error=str(exc))

            # Sleep 2 seconds before emitting next telemetry tick
            await asyncio.sleep(2.0)

    log.info("simulator.scenario_complete")


async def _run() -> None:
    """Async main runner for simulator CLI process (`sentinelops-simulator`)."""
    settings = get_settings()
    bus = RedisEventBus(
        redis_url=settings.redis_url,
        telemetry_stream=settings.redis_telemetry_stream,
        incidents_stream=settings.redis_incidents_stream,
    )
    await bus.connect()
    try:
        await run_scenario(bus)
    finally:
        await bus.close()


def main() -> None:
    """CLI entrypoint executed by `sentinelops-simulator` command."""
    import structlog

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(20),
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
