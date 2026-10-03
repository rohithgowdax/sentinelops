"""
Detection Runner Entrypoint for SentinelOps.

Executes as a standalone process (Docker container / CLI script `sentinelops-detector`).
Wires together:
1. `Settings`: Environment configuration.
2. `PostgresOperationalStore`: Database store for querying metrics and checking episode keys.
3. `RedisEventBus`: Stream broker for publishing `IncidentCreatedEvent` instances.
4. `DetectionLoop`: Asynchronous background detection service loop.

Graceful Shutdown:
Handles UNIX signals `SIGINT` (Ctrl+C) and `SIGTERM` (Docker stop) to stop the loop and close connections cleanly.
"""
from __future__ import annotations

import asyncio
import signal
import sys

import structlog

from sentinelops.config.settings import get_settings
from sentinelops.detection.loop import DetectionLoop
from sentinelops.integrations.event_bus.redis_bus import RedisEventBus
from sentinelops.storage.postgres_store import PostgresOperationalStore

# Initialize logger
log = structlog.get_logger(__name__)


async def _run() -> None:
    """
    Asynchronous main entrypoint for the Detection Runner.
    Instantiates infrastructure dependencies, registers signal handlers, and starts DetectionLoop.
    """
    # Step 1: Load environment settings
    settings = get_settings()

    # Step 2: Initialize PostgreSQL OperationalStore connection
    store = PostgresOperationalStore(dsn=settings.postgres_dsn)
    await store.initialize()

    # Step 3: Initialize Redis EventBus connection
    bus = RedisEventBus(
        redis_url=settings.redis_url,
        telemetry_stream=settings.redis_telemetry_stream,
        incidents_stream=settings.redis_incidents_stream,
    )
    await bus.connect()

    # Step 4: Instantiate DetectionLoop orchestrator
    loop = DetectionLoop(
        store=store,
        event_bus=bus,
        rules_path=settings.detection_rules_path,
        interval_seconds=settings.detection_interval_seconds,
    )

    # Step 5: Register graceful shutdown handlers
    def _shutdown(sig: int, _: object) -> None:
        log.info("detection_runner.shutdown_signal", signal=sig)
        loop.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Step 6: Start detection loop and ensure resource cleanup on exit
    try:
        await loop.run()
    finally:
        await bus.close()
        await store.close()
        log.info("detection_runner.stopped")


def main() -> None:
    """CLI entrypoint invoked by `sentinelops-detector` command."""
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(20),
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
