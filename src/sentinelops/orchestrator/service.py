"""
SentinelOps AI Incident Investigation Orchestrator Service.

Role:
Consumes canonical `IncidentCreatedEvent` instances from Redis Stream (`sentinel:incidents`)
and orchestrates the multi-step LangGraph AI investigation loop to produce an evidence-backed
root cause diagnosis.

Architectural Principles:
1. AT-LEAST-ONCE DELIVERY & EXPLICIT ACKNOWLEDGEMENT:
   - Reads events using `XREADGROUP`.
   - Result is saved to PostgreSQL (`store.save_investigation`) FIRST.
   - `XACK` is called ONLY IF database persistence succeeds.
   - If investigation crashes or unhandled error occurs, event remains in Redis PEL.
2. PROVIDER NEUTRALITY:
   - The Orchestrator operates entirely on canonical `Incident` domain objects.
   - Zero inspection of `source_provider` inside the orchestrator or agent nodes.
3. ISOLATED TOOL ACCESS:
   - Agent accesses operational metrics strictly via `TelemetryEvidenceProvider`.
   - Never exposes raw database connections or SQL queries to agent nodes.
4. DURABLE CHECKPOINTING:
   - Uses `incident_id` as the LangGraph `thread_id` for session state tracking.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import time
from typing import Any

import structlog
from langgraph.checkpoint.memory import MemorySaver

from sentinelops.agent.graph import create_investigation_graph
from sentinelops.agent.state import InvestigationState
from sentinelops.capabilities.evidence.telemetry_evidence import PostgresTelemetryEvidenceProvider
from sentinelops.capabilities.llm.provider import DeterministicLLMProvider
from sentinelops.domain.contracts.protocols import (
    KnowledgeProvider,
    LLMProvider,
    TelemetryEvidenceProvider,
)
from sentinelops.domain.models.incident import Incident
from sentinelops.domain.models.investigation import (
    InvestigationResult,
    InvestigationStatus,
)
from sentinelops.integrations.event_bus.redis_bus import RedisEventBus
from sentinelops.storage.postgres_store import PostgresOperationalStore

log = structlog.get_logger(__name__)


class OrchestratorService:
    """
    Background orchestrator service consuming incident stream events and running AI investigations.
    """

    def __init__(
        self,
        event_bus: RedisEventBus,
        store: PostgresOperationalStore,
        evidence_provider: TelemetryEvidenceProvider | None = None,
        llm_provider: LLMProvider | None = None,
        knowledge_provider: KnowledgeProvider | None = None,
        consumer_group: str = "sentinelops-orchestrator",
        consumer_name: str = "orchestrator-1",
        batch_size: int = 5,
        block_ms: int = 2000,
    ) -> None:
        """
        Initialize the Orchestrator service.

        Args:
            event_bus: RedisEventBus instance for stream consumption and acks.
            store: PostgresOperationalStore instance for persisting investigation results.
            evidence_provider: Evidence capability (defaults to PostgresTelemetryEvidenceProvider).
            llm_provider: LLM provider (defaults to DeterministicLLMProvider).
            knowledge_provider: Optional knowledge capability.
            consumer_group: Redis consumer group name.
            consumer_name: Consumer worker name.
            batch_size: Number of incidents to consume per batch.
            block_ms: Redis read blocking timeout in milliseconds.
        """
        self._bus = event_bus
        self._store = store
        self._evidence_provider = evidence_provider or PostgresTelemetryEvidenceProvider(store)
        self._llm_provider = llm_provider or DeterministicLLMProvider()
        self._knowledge_provider = knowledge_provider
        self._group = consumer_group
        self._consumer = consumer_name
        self._batch = batch_size
        self._block = block_ms
        self._running = False

        # In-memory checkpointer for graph state persistence per thread_id
        self._checkpointer = MemorySaver()

        # Compile the LangGraph investigation workflow
        self._graph = create_investigation_graph(
            evidence_provider=self._evidence_provider,
            llm_provider=self._llm_provider,
            knowledge_provider=self._knowledge_provider,
            checkpointer=self._checkpointer,
        )


    async def run(self) -> None:
        """
        Start the background orchestrator consumer loop.

        Ensures consumer group exists and repeatedly processes batches of incident events.
        """
        self._running = True

        # Ensure consumer group is registered on sentinel:incidents stream
        await self._bus.ensure_consumer_group(
            self._bus._incidents_stream, self._group
        )

        log.info(
            "orchestrator.started",
            group=self._group,
            consumer=self._consumer,
        )

        while self._running:
            try:
                await self._process_batch()
            except Exception as exc:
                log.error("orchestrator.batch_error", error=str(exc), exc_info=True)
                await asyncio.sleep(1.0)

    async def process_once(self) -> int:
        """
        Consume and process a single batch of incidents.

        Primary use: Deterministic integration testing.

        Returns:
            int: Number of incidents successfully investigated, saved, and acknowledged.
        """
        await self._bus.ensure_consumer_group(
            self._bus._incidents_stream, self._group
        )
        return await self._process_batch()

    async def _process_batch(self) -> int:
        """
        Fetch a batch of unacknowledged incident messages and investigate each.

        Returns:
            int: Count of successfully investigated and acknowledged incidents.
        """
        count = 0
        async for entry_id, event in self._bus.consume_incidents(
            group=self._group,
            consumer=self._consumer,
            count=self._batch,
            block_ms=self._block,
        ):
            try:
                log.info(
                    "orchestrator.incident_received",
                    incident_id=event.incident.incident_id,
                    entry_id=entry_id,
                )

                # Step 1: Run AI Investigation via LangGraph
                result = await self.investigate_incident(event.incident)

                # Step 2: Persist durable InvestigationResult to PostgreSQL
                await self._store.save_investigation(result)

                # Step 3: Acknowledge Redis stream message
                await self._bus.ack_incident(self._group, entry_id)
                count += 1

                log.info(
                    "orchestrator.investigation_completed",
                    incident_id=result.incident_id,
                    status=result.status.value,
                    confidence=result.confidence,
                    root_cause=result.diagnosis.root_cause if result.diagnosis else None,
                )
            except Exception as exc:
                log.error(
                    "orchestrator.investigation_error",
                    incident_id=event.incident.incident_id,
                    entry_id=entry_id,
                    error=str(exc),
                    exc_info=True,
                )
                # Do NOT ACK: leaves message in Redis PEL for retry/recovery
        return count

    async def investigate_incident(self, incident: Incident) -> InvestigationResult:
        """
        Execute the LangGraph AI investigation workflow for a given Incident.

        Args:
            incident: Canonical `Incident` entity to investigate.

        Returns:
            `InvestigationResult` domain entity containing diagnosis, evidence, and steps.
        """
        start_time = time.time()

        initial_state: InvestigationState = {
            "incident": incident,
            "investigation_plan": None,
            "current_step": 0,
            "iteration": 0,
            "max_iterations": 3,
            "evidence": [],
            "hypotheses": [],
            "selected_hypothesis": None,
            "diagnosis": None,
            "confidence": 0.0,
            "verification_result": None,
            "status": InvestigationStatus.INVESTIGATING,
            "errors": [],
            "tool_calls_summary": [],
            "start_time_iso": datetime.now(tz=timezone.utc).isoformat(),
            "final_result": None,
        }

        # Use canonical incident_id as thread_id for checkpointing
        config: dict[str, Any] = {
            "configurable": {"thread_id": incident.incident_id}
        }

        try:
            final_state = await self._graph.ainvoke(initial_state, config=config)
            result = final_state.get("final_result")

            if result is None:
                # Fallback if graph terminated unexpectedly without finalize
                result = InvestigationResult(
                    incident_id=incident.incident_id,
                    status=InvestigationStatus.INVESTIGATION_FAILED,
                    confidence=0.0,
                    failure_reason="Graph execution concluded without producing final_result",
                    duration_seconds=round(time.time() - start_time, 3),
                )

            return result

        except Exception as exc:
            log.error(
                "orchestrator.graph_exception",
                incident_id=incident.incident_id,
                error=str(exc),
                exc_info=True,
            )
            return InvestigationResult(
                incident_id=incident.incident_id,
                status=InvestigationStatus.INVESTIGATION_FAILED,
                confidence=0.0,
                failure_reason=f"Graph execution failed with error: {str(exc)}",
                duration_seconds=round(time.time() - start_time, 3),
            )

    def stop(self) -> None:
        """Signal the orchestrator loop to stop gracefully."""
        self._running = False
        log.info("orchestrator.stopping")
