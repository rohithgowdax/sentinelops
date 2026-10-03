"""
SentinelOps Orchestrator Runner Entrypoint.

Executes as a standalone process (Docker container / CLI script `sentinelops-orchestrator`).
Wires together:
1. `Settings`: Environment configuration.
2. `PostgresOperationalStore`: Database store for telemetry and investigations.
3. `RedisEventBus`: Stream broker for consuming `sentinel:incidents`.
4. `PostgresTelemetryEvidenceProvider`: Evidence capability adapter.
5. `DeterministicLLMProvider`: Pluggable LLM reasoning engine.
6. `OrchestratorService`: Incident event consumer and LangGraph investigator.

Graceful Shutdown:
Handles UNIX signals `SIGINT` (Ctrl+C) and `SIGTERM` (Docker stop) to stop the consumer loop
and close database/stream connections cleanly.
"""
from __future__ import annotations

import asyncio
import signal
import sys

import structlog

from sentinelops.capabilities.evidence.telemetry_evidence import PostgresTelemetryEvidenceProvider
from sentinelops.capabilities.llm.provider import DeterministicLLMProvider
from sentinelops.config.settings import get_settings
from sentinelops.integrations.event_bus.redis_bus import RedisEventBus
from sentinelops.orchestrator.service import OrchestratorService
from sentinelops.storage.postgres_store import PostgresOperationalStore

log = structlog.get_logger(__name__)


async def _run() -> None:
    """
    Asynchronous main entrypoint for the Orchestrator Runner.
    Instantiates dependencies, registers signal handlers, and starts the orchestrator loop.
    """
    settings = get_settings()

    # Step 1: Initialize PostgreSQL OperationalStore
    store = PostgresOperationalStore(dsn=settings.postgres_dsn)
    await store.initialize()

    # Step 2: Initialize Redis EventBus
    bus = RedisEventBus(
        redis_url=settings.redis_url,
        telemetry_stream=settings.redis_telemetry_stream,
        incidents_stream=settings.redis_incidents_stream,
    )
    await bus.connect()

    # Step 3: Initialize Evidence Capability and LLM Provider
    evidence_provider = PostgresTelemetryEvidenceProvider(store)
    llm_provider = DeterministicLLMProvider()

    # Step 4: Instantiate OrchestratorService
    orchestrator = OrchestratorService(
        event_bus=bus,
        store=store,
        evidence_provider=evidence_provider,
        llm_provider=llm_provider,
        consumer_group=settings.orchestrator_consumer_group,
        consumer_name="orchestrator-1",
        batch_size=settings.orchestrator_batch_size,
        block_ms=settings.orchestrator_block_ms,
    )

    # Step 5: Register graceful shutdown signal handlers
    def _shutdown(sig: int, _: object) -> None:
        log.info("orchestrator_runner.shutdown_signal", signal=sig)
        orchestrator.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Step 6: Start orchestrator loop and guarantee resource cleanup
    try:
        await orchestrator.run()
    finally:
        await bus.close()
        await store.close()
        log.info("orchestrator_runner.stopped")


def main() -> None:
    """CLI entrypoint invoked by `sentinelops-orchestrator` command."""
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(20),
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
