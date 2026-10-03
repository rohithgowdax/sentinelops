"""
Capability contracts and protocols for SentinelOps.

These `typing.Protocol` definitions define structural interfaces for core platform capabilities.
The business logic in SentinelOps depends strictly on these abstract protocols, adhering
to the Dependency Inversion Principle (DIP).

Protocols Defined:
1. `EventBus`: Messaging broker interface (implemented by `RedisEventBus`).
2. `OperationalStore`: Database persistence interface (implemented by `PostgresOperationalStore`).
3. `TelemetryAdapter`: External payload normalizer interface (implemented by `OtelLikeAdapter` and `CustomJsonAdapter`).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from sentinelops.domain.models.events import (
    IncidentCreatedEvent,
    TelemetryReceivedEvent,
)
from sentinelops.domain.models.incident import Incident
from sentinelops.domain.models.knowledge import (
    KnowledgeChunk,
    KnowledgeQuery,
    KnowledgeResult,
)
from sentinelops.domain.models.telemetry import TelemetryRecord



@runtime_checkable
class EventBus(Protocol):
    """
    Asynchronous EventBus protocol for publishing and consuming system domain events.

    Implementations must support streaming semantics, consumer groups, and explicit message ACKs.
    Production Implementation: `sentinelops.integrations.event_bus.redis_bus.RedisEventBus`
    """

    async def publish_telemetry(self, event: TelemetryReceivedEvent) -> str:
        """
        Publish a normalized telemetry event to the telemetry stream ('sentinel:telemetry').

        Args:
            event: The `TelemetryReceivedEvent` envelope containing a canonical `TelemetryRecord`.

        Returns:
            str: Broker-assigned entry ID (e.g. Redis stream ID '1696172232000-0').
        """
        ...

    async def publish_incident(self, event: IncidentCreatedEvent) -> str:
        """
        Publish a detected incident event to the incidents stream ('sentinel:incidents').

        Args:
            event: The `IncidentCreatedEvent` envelope containing the canonical `Incident`.

        Returns:
            str: Broker-assigned entry ID.
        """
        ...

    async def consume_telemetry(
        self,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 2000,
    ) -> AsyncIterator[tuple[str, TelemetryReceivedEvent]]:
        """
        Consume telemetry events as a worker in a named consumer group.

        Args:
            group: Consumer group name (e.g. 'sentinelops-workers').
            consumer: Individual worker identifier (e.g. 'worker-1').
            count: Maximum batch size of messages to retrieve in one iteration.
            block_ms: Time in milliseconds to block waiting for new messages.

        Yields:
            Tuple of (stream_entry_id, TelemetryReceivedEvent).
            Caller MUST call `ack_telemetry` upon successful processing.
        """
        ...

    async def ack_telemetry(self, group: str, entry_id: str) -> None:
        """
        Acknowledge successful processing of a telemetry message.

        Args:
            group: Consumer group name.
            entry_id: Broker entry ID returned during consumption.
        """
        ...

    async def consume_incidents(
        self,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 2000,
    ) -> AsyncIterator[tuple[str, IncidentCreatedEvent]]:
        """
        Consume incident events as a worker in a named consumer group.

        Args:
            group: Consumer group name.
            consumer: Individual worker identifier.
            count: Maximum batch size of messages to retrieve.
            block_ms: Time in milliseconds to block waiting.

        Yields:
            Tuple of (stream_entry_id, IncidentCreatedEvent).
        """
        ...

    async def ack_incident(self, group: str, entry_id: str) -> None:
        """
        Acknowledge successful processing of an incident message.

        Args:
            group: Consumer group name.
            entry_id: Broker entry ID to acknowledge.
        """
        ...


@runtime_checkable
class OperationalStore(Protocol):
    """
    Persistence store protocol for canonical telemetry metrics and incident records.

    Implementations must guarantee idempotency on primary keys (`event_id` and `incident_id`).
    Production Implementation: `sentinelops.storage.postgres_store.PostgresOperationalStore`
    """

    async def save_telemetry(self, record: TelemetryRecord) -> None:
        """
        Persist a canonical telemetry record.

        Requirement: Must be idempotent (e.g. SQL `ON CONFLICT (event_id) DO NOTHING`).

        Args:
            record: The `TelemetryRecord` instance to store.
        """
        ...

    async def query_recent_metrics(
        self,
        service_name: str,
        metric_name: str,
        since: datetime,
    ) -> list[TelemetryRecord]:
        """
        Query historical metric telemetry for a specific service within a look-back window.

        Requirement:
        - Results MUST be filtered on canonical fields (`service_name`, `metric_name`, `timestamp >= since`).
        - Results MUST NOT branch or filter on `provider`.
        - Results MUST be ordered by `timestamp` ascending.

        Args:
            service_name: Logical service identifier (e.g. 'payments-service').
            metric_name: Canonical metric name (e.g. 'http.error_rate').
            since: UTC datetime start bound for the time window.

        Returns:
            List of matching `TelemetryRecord` objects sorted by timestamp ASC.
        """
        ...

    async def save_incident(self, incident: Incident) -> None:
        """
        Persist a newly created canonical incident.

        Requirement: Must be idempotent on `incident_id`.

        Args:
            incident: The `Incident` domain model to save.
        """
        ...

    async def get_incident(self, incident_id: str) -> Incident | None:
        """
        Retrieve a single incident by its unique ID.

        Args:
            incident_id: Incident ID string (e.g. 'INC-A1B2C3D4').

        Returns:
            `Incident` model if found, or `None` if no matching record exists.
        """
        ...

    async def list_incidents(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Incident]:
        """
        Retrieve paginated list of canonical incidents ordered by `created_at` DESC.

        Args:
            limit: Maximum number of incidents to return.
            offset: Pagination offset index.

        Returns:
            List of `Incident` domain objects.
        """
        ...

    async def get_active_episode(self, episode_key: str) -> Incident | None:
        """
        Retrieve an active (OPEN or INVESTIGATING) incident matching an episode key.

        Used for deduplication: prevents duplicate incident creation while an episode is active.

        Args:
            episode_key: Composite string key ('rule_id::service::env').

        Returns:
            `Incident` if an active episode exists, or `None`.
        """
        ...

    async def save_investigation(self, result: Any) -> None:
        """
        Persist a completed or partial InvestigationResult.

        Must be idempotent on `incident_id`.

        Args:
            result: The `InvestigationResult` domain object.
        """
        ...

    async def get_investigation(self, incident_id: str) -> Any | None:
        """
        Retrieve the latest InvestigationResult for an incident ID.

        Args:
            incident_id: The incident ID to query.

        Returns:
            `InvestigationResult` if found, else None.
        """
        ...


@runtime_checkable
class TelemetryEvidenceProvider(Protocol):
    """
    Capability protocol providing structured evidence queries over operational data.

    Decoupling Rule:
    LangGraph nodes interact with this capability interface rather than executing
    SQL or Redis commands directly.
    """

    async def query_recent_telemetry(
        self,
        service_name: str,
        metric_name: str,
        lookback_seconds: int = 300,
    ) -> dict[str, Any]:
        """
        Query recent canonical telemetry data points for a service and metric.

        Args:
            service_name: Name of target service (e.g. 'payments-service').
            metric_name: Canonical metric name (e.g. 'http.error_rate').
            lookback_seconds: Look-back duration in seconds.

        Returns:
            Structured dictionary with window, sample count, observed_avg, observed_max.
        """
        ...

    async def compare_telemetry_baseline(
        self,
        service_name: str,
        metric_name: str,
        current_window_seconds: int = 120,
        baseline_window_seconds: int = 600,
    ) -> dict[str, Any]:
        """
        Compare current metric behavior against historical baseline.

        Args:
            service_name: Name of target service.
            metric_name: Canonical metric name.
            current_window_seconds: Window duration for current degraded state.
            baseline_window_seconds: Window duration for historical baseline state.

        Returns:
            Structured dictionary with baseline average, current average, ratio/deviation.
        """
        ...

    async def get_incident_trigger_context(
        self,
        incident: Incident,
    ) -> dict[str, Any]:
        """
        Extract structured trigger context and initial evidence from canonical incident.

        Args:
            incident: Canonical `Incident` domain model.

        Returns:
            Structured dictionary of trigger parameters and observations.
        """
        ...


@runtime_checkable
class KnowledgeProvider(Protocol):
    """
    Capability protocol for searching and querying organizational knowledge.

    Invariants:
    - Provider-neutral: callers request KnowledgeQuery, receiving canonical KnowledgeResult.
    - Implementations handle vector DB indexing, sparse/dense search, filtering, and fusion.
    """

    async def search(
        self,
        query: KnowledgeQuery,
    ) -> list[KnowledgeResult]:
        """
        Execute semantic and metadata-filtered search over operational knowledge.

        Args:
            query: Canonical `KnowledgeQuery`.

        Returns:
            List of `KnowledgeResult` items ordered by relevance score.
        """
        ...

    async def index_chunks(
        self,
        chunks: list[KnowledgeChunk],
    ) -> int:
        """
        Idempotently index knowledge chunks into the underlying storage engine.

        Args:
            chunks: List of canonical `KnowledgeChunk` items.

        Returns:
            Count of successfully indexed chunks.
        """
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """
    Protocol for generating dense vector representations for queries and documents.
    """

    @property
    def dimension(self) -> int:
        """Dimensionality of the output embedding vector."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Generate vector embedding for a single search query."""
        ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Generate vector embeddings for a batch of documents/chunks."""
        ...


@runtime_checkable
class RerankerProvider(Protocol):
    """
    Protocol for reranking candidate search results.
    """

    async def rerank(
        self,
        query: str,
        results: list[KnowledgeResult],
        top_k: int = 5,
    ) -> list[KnowledgeResult]:
        """
        Rerank and filter candidate search results.

        Args:
            query: The search query string.
            results: Candidate `KnowledgeResult` items.
            top_k: Maximum number of reranked items to return.

        Returns:
            Reranked list of `KnowledgeResult` items.
        """
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """
    Pluggable LLM provider abstraction for SentinelOps investigation nodes.

    Decoupling Rule:
    Agent nodes call this boundary. Concrete implementations can invoke
    cloud models (OpenAI, Gemini, Anthropic) or deterministic rule-assisted providers for tests.
    """

    async def generate_plan(
        self,
        incident: Incident,
        available_capabilities: list[str],
    ) -> Any:
        """
        Generate structured InvestigationPlan based on incident symptoms.

        Args:
            incident: Canonical `Incident` under investigation.
            available_capabilities: List of available capability strings.

        Returns:
            `InvestigationPlan` domain model.
        """
        ...

    async def generate_knowledge_queries(
        self,
        incident: Incident,
        plan: Any,
        telemetry_evidence: list[Any],
    ) -> list[KnowledgeQuery]:
        """
        Generate targeted search queries for operational knowledge based on incident symptoms.

        Args:
            incident: Canonical `Incident`.
            plan: Current `InvestigationPlan`.
            telemetry_evidence: Collected live telemetry evidence.

        Returns:
            List of `KnowledgeQuery` objects to execute against KnowledgeProvider.
        """
        ...


    async def analyze_hypotheses(
        self,
        incident: Incident,
        evidence: list[Any],
    ) -> list[Any]:
        """
        Formulate structured hypotheses supported by collected evidence.

        Args:
            incident: Canonical `Incident`.
            evidence: List of `InvestigationEvidence` gathered so far.

        Returns:
            List of `Hypothesis` domain models.
        """
        ...

    async def generate_diagnosis(
        self,
        incident: Incident,
        evidence: list[Any],
        hypothesis: Any,
    ) -> Any:
        """
        Synthesize evidence into a structured root cause Diagnosis.

        Args:
            incident: Canonical `Incident`.
            evidence: List of `InvestigationEvidence`.
            hypothesis: Selected `Hypothesis`.

        Returns:
            `Diagnosis` domain model.
        """
        ...

    async def verify_diagnosis(
        self,
        incident: Incident,
        evidence: list[Any],
        diagnosis: Any,
    ) -> Any:
        """
        Evaluate if diagnosis is adequately supported by evidence without contradiction.

        Args:
            incident: Canonical `Incident`.
            evidence: List of `InvestigationEvidence`.
            diagnosis: Candidate `Diagnosis`.

        Returns:
            `VerificationResult` domain model.
        """
        ...


@runtime_checkable
class TelemetryAdapter(Protocol):
    """
    Adapter protocol for converting proprietary vendor JSON formats into canonical TelemetryRecords.

    Implementations:
    - `OtelLikeAdapter`: Normalizes OpenTelemetry JSON payloads.
    - `CustomJsonAdapter`: Normalizes custom non-OTel JSON payloads.
    """

    @property
    def provider(self) -> str:
        """
        Identifier string for the source provider category (e.g. 'otel', 'custom_json').
        """
        ...

    @property
    def integration_id(self) -> str:
        """
        Unique instance tag for this adapter (e.g. 'otel-json-v1').
        """
        ...

    def normalize(self, raw: dict[str, Any]) -> TelemetryRecord:
        """
        Synchronously parse and normalize a raw vendor dictionary into a canonical TelemetryRecord.

        Rules:
        - Must raise `ValueError` for structurally invalid or missing required vendor fields.
        - Must set `raw_payload` to the input dictionary for auditability.
        - Must normalize unit scales (e.g. converting percent 0..100 to ratio 0..1).

        Args:
            raw: Raw Python dictionary parsed from incoming JSON.

        Returns:
            Normalized `TelemetryRecord` domain object.
        """
        ...
