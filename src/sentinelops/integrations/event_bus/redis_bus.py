"""
Redis Streams EventBus implementation for SentinelOps.

Implements the `EventBus` protocol using Redis Streams (`XADD`, `XREADGROUP`, `XACK`).

Architectural Decision (ADR-002):
- Streams Used:
  1. `sentinel:telemetry`: Transport for normalized telemetry events emitted by adapters.
  2. `sentinel:incidents`: Transport for incidents created by the Detection Loop.
- Consumer Groups:
  Provides at-least-once delivery semantics across worker instances.
- Explicit ACK (Acknowledgement):
  Messages are ONLY acknowledged via `XACK` after worker persistence succeeds.
  Unacknowledged failed messages remain in the Pending-Entries List (PEL) to guarantee zero message loss.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

import redis.asyncio as aioredis
import structlog

from sentinelops.domain.models.events import (
    IncidentCreatedEvent,
    TelemetryReceivedEvent,
)

# Initialize logger
log = structlog.get_logger(__name__)


class RedisEventBus:
    """
    Production implementation of the `EventBus` protocol backed by Redis Streams.

    Methods are asynchronous and operate using `redis.asyncio`.
    Supports async context manager usage (`async with RedisEventBus(...)`).
    """

    def __init__(
        self,
        redis_url: str,
        telemetry_stream: str = "sentinel:telemetry",
        incidents_stream: str = "sentinel:incidents",
    ) -> None:
        """
        Initialize the Redis EventBus configuration.

        Args:
            redis_url: Redis DSN connection string (e.g. 'redis://localhost:6379/0').
            telemetry_stream: Redis stream key for telemetry events (default: 'sentinel:telemetry').
            incidents_stream: Redis stream key for incident events (default: 'sentinel:incidents').
        """
        self._redis_url = redis_url
        self._telemetry_stream = telemetry_stream
        self._incidents_stream = incidents_stream
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        """
        Establish an asynchronous connection pool to Redis and verify connectivity with PING.

        Raises:
            redis.exceptions.ConnectionError: If Redis server is unreachable.
        """
        self._client = aioredis.from_url(
            self._redis_url,
            decode_responses=True,  # Decode byte responses to standard python str
            socket_connect_timeout=5,
        )
        # Test connection
        await self._client.ping()
        log.info("redis_event_bus.connected", url=self._redis_url)

    async def close(self) -> None:
        """Close the underlying Redis client connection pool gracefully."""
        if self._client:
            await self._client.aclose()
            self._client = None
            log.info("redis_event_bus.closed")

    async def __aenter__(self) -> "RedisEventBus":
        """Async context manager entrance: connects to Redis."""
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        """Async context manager exit: closes Redis connection."""
        await self.close()

    @property
    def _redis(self) -> aioredis.Redis:
        """
        Internal property returning connected Redis client or raising RuntimeError.
        """
        if self._client is None:
            raise RuntimeError("RedisEventBus is not connected. Call connect() first.")
        return self._client

    # ── Consumer Group Management ──────────────────────────────────────────────

    async def ensure_consumer_group(self, stream: str, group: str) -> None:
        """
        Create a Redis consumer group if it does not already exist.

        Uses `XGROUP CREATE stream group 0 MKSTREAM`.
        - `id="0"`: Group will start consuming from the beginning of the stream.
        - `mkstream=True`: Automatically creates the stream key if missing.

        Args:
            stream: Stream key name (e.g. 'sentinel:telemetry').
            group: Consumer group name (e.g. 'sentinelops-workers').
        """
        try:
            await self._redis.xgroup_create(stream, group, id="0", mkstream=True)
            log.info("consumer_group.created", stream=stream, group=group)
        except aioredis.ResponseError as exc:
            # Handle BUSYGROUP error gracefully if the group was created by another worker
            if "BUSYGROUP" in str(exc):
                log.debug("consumer_group.already_exists", stream=stream, group=group)
            else:
                raise

    # ── Event Publishing (XADD) ────────────────────────────────────────────────

    async def publish_telemetry(self, event: TelemetryReceivedEvent) -> str:
        """
        Publish a canonical TelemetryReceivedEvent to the telemetry stream via `XADD`.

        Args:
            event: The TelemetryReceivedEvent object.

        Returns:
            str: Assigned Redis stream message ID (e.g. '1696172232000-0').
        """
        # Serialize Pydantic event object to JSON string
        payload = event.model_dump_json()

        # Execute XADD command
        entry_id: str = await self._redis.xadd(  # type: ignore[assignment]
            self._telemetry_stream,
            {"event_id": event.event_id, "payload": payload},
        )
        log.debug(
            "event_bus.telemetry.published",
            event_id=event.event_id,
            entry_id=entry_id,
        )
        return entry_id

    async def publish_incident(self, event: IncidentCreatedEvent) -> str:
        """
        Publish a canonical IncidentCreatedEvent to the incidents stream via `XADD`.

        Args:
            event: The IncidentCreatedEvent object.

        Returns:
            str: Assigned Redis stream message ID.
        """
        # Serialize event model to JSON string
        payload = event.model_dump_json()

        # Execute XADD command
        entry_id: str = await self._redis.xadd(  # type: ignore[assignment]
            self._incidents_stream,
            {"event_id": event.event_id, "payload": payload},
        )
        log.info(
            "event_bus.incident.published",
            incident_id=event.incident.incident_id,
            event_id=event.event_id,
            entry_id=entry_id,
        )
        return entry_id

    # ── Event Consumption (XREADGROUP) ─────────────────────────────────────────

    async def consume_telemetry(
        self,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 2000,
    ) -> AsyncIterator[tuple[str, TelemetryReceivedEvent]]:
        """
        Consume unread telemetry messages from the telemetry stream using `XREADGROUP`.

        Reads messages using the special ID `>` (undelivered messages).
        Messages are NOT automatically acknowledged; the caller must invoke `ack_telemetry`.

        Args:
            group: Consumer group name.
            consumer: Individual consumer worker ID.
            count: Maximum batch count of messages to fetch.
            block_ms: Milliseconds to wait/block if stream is empty.

        Yields:
            Tuples of (entry_id, TelemetryReceivedEvent).
        """
        # Execute XREADGROUP GROUP <group> <consumer> COUNT <count> BLOCK <block_ms> STREAMS sentinel:telemetry >
        results = await self._redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={self._telemetry_stream: ">"},
            count=count,
            block=block_ms,
        )
        if not results:
            return

        # Unpack stream response structure: [ [stream_name, [ (entry_id, fields_dict), ... ]] ]
        for _stream, messages in results:
            for entry_id, fields in messages:
                try:
                    # Parse JSON payload back into Pydantic domain event model
                    event = TelemetryReceivedEvent.model_validate_json(
                        fields["payload"]
                    )
                    yield entry_id, event
                except Exception as exc:
                    log.error(
                        "event_bus.telemetry.parse_error",
                        entry_id=entry_id,
                        error=str(exc),
                    )
                    # CRITICAL: Do NOT ack corrupt messages; leave in PEL for inspection/DLQ

    async def ack_telemetry(self, group: str, entry_id: str) -> None:
        """
        Acknowledge a processed telemetry message using `XACK`.

        Removes the message entry from the group's Pending-Entries List (PEL).

        Args:
            group: Consumer group name.
            entry_id: Redis stream message ID to acknowledge.
        """
        await self._redis.xack(self._telemetry_stream, group, entry_id)
        log.debug("event_bus.telemetry.acked", group=group, entry_id=entry_id)

    async def consume_incidents(
        self,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 2000,
    ) -> AsyncIterator[tuple[str, IncidentCreatedEvent]]:
        """
        Consume unread incident messages from the incidents stream using `XREADGROUP`.

        Args:
            group: Consumer group name.
            consumer: Consumer worker ID.
            count: Maximum message count.
            block_ms: Block duration in ms.

        Yields:
            Tuples of (entry_id, IncidentCreatedEvent).
        """
        results = await self._redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={self._incidents_stream: ">"},
            count=count,
            block=block_ms,
        )
        if not results:
            return

        for _stream, messages in results:
            for entry_id, fields in messages:
                try:
                    event = IncidentCreatedEvent.model_validate_json(
                        fields["payload"]
                    )
                    yield entry_id, event
                except Exception as exc:
                    log.error(
                        "event_bus.incident.parse_error",
                        entry_id=entry_id,
                        error=str(exc),
                    )

    async def ack_incident(self, group: str, entry_id: str) -> None:
        """
        Acknowledge a processed incident message using `XACK`.

        Args:
            group: Consumer group name.
            entry_id: Redis stream entry ID.
        """
        await self._redis.xack(self._incidents_stream, group, entry_id)
        log.debug("event_bus.incident.acked", group=group, entry_id=entry_id)
