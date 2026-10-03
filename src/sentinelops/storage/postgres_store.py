"""
PostgreSQL OperationalStore implementation for SentinelOps.

Implements the `OperationalStore` protocol using SQLAlchemy 2.0 Async (`AsyncEngine`, `asyncpg`).

Repository Pattern Architecture:
- Encapsulates database queries, transactions, and session management.
- Performs bidirectional translation between SQLAlchemy ORM rows (`TelemetryRow`, `IncidentRow`)
  and canonical Pydantic domain entities (`TelemetryRecord`, `Incident`).
- Guarantees Idempotency: Uses PostgreSQL `INSERT ... ON CONFLICT (event_id) DO NOTHING`
  and `ON CONFLICT (incident_id) DO NOTHING`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sentinelops.domain.models.incident import (
    EvidenceItem,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    TriggerType,
)
from sentinelops.domain.models.investigation import (
    Diagnosis,
    InvestigationEvidence,
    InvestigationResult,
    InvestigationStatus,
    InvestigationStep,
)
from sentinelops.domain.models.telemetry import (
    LogRecord,
    MetricObservation,
    ResourceIdentity,
    Severity,
    SignalType,
    TelemetryRecord,
    TelemetrySource,
)
from sentinelops.storage.orm_models import Base, IncidentRow, InvestigationRow, TelemetryRow

# Initialize logger
log = structlog.get_logger(__name__)


class PostgresOperationalStore:
    """
    PostgreSQL persistence engine implementing the `OperationalStore` protocol.

    Manages async database connection pools and executes CRUD operations for telemetry
    and incidents.
    """

    def __init__(self, dsn: str, pool_size: int = 5) -> None:
        """
        Initialize the PostgreSQL Operational Store parameters.

        Args:
            dsn: PostgreSQL async DSN string (e.g. 'postgresql+asyncpg://user:pass@localhost:5432/db').
            pool_size: Connection pool size limit for asyncpg.
        """
        self._dsn = dsn
        self._pool_size = pool_size
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def initialize(self) -> None:
        """
        Initialize the SQLAlchemy async engine, session factory, and auto-create database tables.

        Executes `Base.metadata.create_all` against PostgreSQL to ensure schemas exist.
        """
        # Create asynchronous SQLAlchemy engine
        self._engine = create_async_engine(
            self._dsn,
            pool_size=self._pool_size,
            echo=False,
            future=True,
        )

        # Create sessionmaker bound to the engine
        self._session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

        # Auto-create tables on startup
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        log.info("operational_store.initialized", dsn=self._dsn.split("@")[-1])

    async def close(self) -> None:
        """Dispose of the connection pool gracefully during service shutdown."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            log.info("operational_store.closed")

    @property
    def _session(self) -> async_sessionmaker[AsyncSession]:
        """
        Internal helper returning session factory or raising RuntimeError if uninitialized.
        """
        if self._session_factory is None:
            raise RuntimeError(
                "PostgresOperationalStore not initialized. Call initialize() first."
            )
        return self._session_factory

    # ── Telemetry CRUD Operations ──────────────────────────────────────────────

    async def save_telemetry(self, record: TelemetryRecord) -> None:
        """
        Persist a canonical TelemetryRecord to the PostgreSQL database.

        Idempotency:
        Uses PostgreSQL dialect `pg_insert().on_conflict_do_nothing(index_elements=['event_id'])`.
        If a duplicate `event_id` is written by worker retries, PostgreSQL ignores the insert.

        Args:
            record: Canonical `TelemetryRecord` domain entity.
        """
        # Step 1: Map domain entity to ORM schema column representation
        row = _telemetry_to_row(record)

        # Step 2: Build idempotent PostgreSQL upsert statement
        stmt = pg_insert(TelemetryRow).values(
            event_id=row.event_id,
            timestamp=row.timestamp,
            signal_type=row.signal_type,
            provider=row.provider,
            integration_id=row.integration_id,
            service_name=row.service_name,
            service_namespace=row.service_namespace,
            service_version=row.service_version,
            environment=row.environment,
            host_name=row.host_name,
            metric_name=row.metric_name,
            metric_value=row.metric_value,
            metric_unit=row.metric_unit,
            metric_dimensions=row.metric_dimensions,
            log_severity=row.log_severity,
            log_message=row.log_message,
            trace_id=row.trace_id,
            span_id=row.span_id,
            raw_payload=row.raw_payload,
            attributes=row.attributes,
        ).on_conflict_do_nothing(index_elements=["event_id"])

        # Step 3: Execute transaction
        async with self._session() as session:
            await session.execute(stmt)
            await session.commit()

        log.debug("store.telemetry.saved", event_id=record.event_id)

    async def query_recent_metrics(
        self,
        service_name: str,
        metric_name: str,
        since: datetime,
    ) -> list[TelemetryRecord]:
        """
        Query historical metric samples for a service within a look-back window.

        Filtering Strategy:
        - Filters by `service_name == service_name`
        - Filters by `metric_name == metric_name`
        - Filters by `timestamp >= since`
        - Filters by `signal_type == 'metric'`
        - Orders by `timestamp ASC` (crucial for Detection Engine window aggregation)

        Important: This query operates ENTIRELY on provider-neutral canonical fields.

        Args:
            service_name: Target service name (e.g. 'payments-service').
            metric_name: Canonical metric name (e.g. 'http.error_rate').
            since: UTC datetime bound for the look-back window.

        Returns:
            List of matching `TelemetryRecord` domain objects.
        """
        stmt = (
            select(TelemetryRow)
            .where(
                TelemetryRow.service_name == service_name,
                TelemetryRow.metric_name == metric_name,
                TelemetryRow.timestamp >= since,
                TelemetryRow.signal_type == SignalType.METRIC.value,
            )
            .order_by(TelemetryRow.timestamp.asc())
        )

        async with self._session() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()

        # Map ORM rows back to canonical TelemetryRecord domain objects
        return [_row_to_telemetry(r) for r in rows]

    # ── Incident CRUD Operations ───────────────────────────────────────────────

    async def save_incident(self, incident: Incident) -> None:
        """
        Persist a canonical Incident to the PostgreSQL database.

        Idempotency:
        Uses `ON CONFLICT (incident_id) DO NOTHING` to ignore duplicate saves.

        Args:
            incident: Canonical `Incident` domain model.
        """
        row_data = _incident_to_dict(incident)
        stmt = pg_insert(IncidentRow).values(**row_data).on_conflict_do_nothing(
            index_elements=["incident_id"]
        )

        async with self._session() as session:
            await session.execute(stmt)
            await session.commit()

        log.info("store.incident.saved", incident_id=incident.incident_id)

    async def get_incident(self, incident_id: str) -> Incident | None:
        """
        Retrieve an incident by primary key `incident_id`.

        Args:
            incident_id: Incident identifier string.

        Returns:
            `Incident` domain object if found, else `None`.
        """
        stmt = select(IncidentRow).where(IncidentRow.incident_id == incident_id)
        async with self._session() as session:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

        return _row_to_incident(row) if row else None

    async def list_incidents(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Incident]:
        """
        List incidents ordered by creation time descending.

        Args:
            limit: Pagination limit count.
            offset: Pagination offset index.

        Returns:
            List of `Incident` domain models.
        """
        stmt = (
            select(IncidentRow)
            .order_by(IncidentRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._session() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [_row_to_incident(r) for r in rows]

    async def get_active_episode(self, episode_key: str) -> Incident | None:
        """
        Find an active (OPEN or INVESTIGATING) incident matching an episode key.

        Used by the Detection Loop to deduplicate incidents during continuous outages.

        Args:
            episode_key: Composite deduplication string ('rule_id::service::env').

        Returns:
            Active `Incident` entity if found, else `None`.
        """
        stmt = (
            select(IncidentRow)
            .where(
                IncidentRow.episode_key == episode_key,
                IncidentRow.status.in_([
                    IncidentStatus.OPEN.value,
                    IncidentStatus.INVESTIGATING.value,
                ]),
            )
            .order_by(IncidentRow.created_at.desc())
            .limit(1)
        )
        async with self._session() as session:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

        return _row_to_incident(row) if row else None

    # ── Investigation CRUD Operations ──────────────────────────────────────────

    async def save_investigation(self, result: InvestigationResult) -> None:
        """
        Persist an InvestigationResult to the PostgreSQL database.

        Idempotency:
        Uses `ON CONFLICT (incident_id) DO UPDATE` to ensure existing investigations
        are updated with the latest finalized status and evidence.

        Args:
            result: Canonical `InvestigationResult` domain entity.
        """
        row_data = _investigation_to_dict(result)
        stmt = (
            pg_insert(InvestigationRow)
            .values(**row_data)
            .on_conflict_do_update(
                index_elements=["incident_id"],
                set_={
                    "status": row_data["status"],
                    "confidence": row_data["confidence"],
                    "diagnosis": row_data["diagnosis"],
                    "supporting_evidence": row_data["supporting_evidence"],
                    "investigation_steps": row_data["investigation_steps"],
                    "tool_calls_summary": row_data["tool_calls_summary"],
                    "duration_seconds": row_data["duration_seconds"],
                    "iteration_count": row_data["iteration_count"],
                    "failure_reason": row_data["failure_reason"],
                    "completed_at": row_data["completed_at"],
                },
            )
        )

        async with self._session() as session:
            await session.execute(stmt)
            await session.commit()

        log.info(
            "store.investigation.saved",
            incident_id=result.incident_id,
            status=result.status.value,
        )

    async def get_investigation(self, incident_id: str) -> InvestigationResult | None:
        """
        Retrieve an investigation result by primary key `incident_id`.

        Args:
            incident_id: Canonical incident ID string.

        Returns:
            `InvestigationResult` domain object if found, else `None`.
        """
        stmt = select(InvestigationRow).where(InvestigationRow.incident_id == incident_id)
        async with self._session() as session:
            res = await session.execute(stmt)
            row = res.scalar_one_or_none()

        return _row_to_investigation(row) if row else None



# ── Entity Mapping Translators (Domain <-> ORM) ──────────────────────────────


def _telemetry_to_row(r: TelemetryRecord) -> TelemetryRow:
    """
    Translate a canonical TelemetryRecord domain entity into a SQLAlchemy TelemetryRow.

    Args:
        r: Domain model instance.

    Returns:
        ORM row model instance.
    """
    row = TelemetryRow()
    row.event_id = r.event_id
    row.timestamp = r.timestamp
    row.signal_type = r.signal_type.value
    row.provider = r.source.provider
    row.integration_id = r.source.integration_id
    row.service_name = r.resource.service_name
    row.service_namespace = r.resource.service_namespace
    row.service_version = r.resource.service_version
    row.environment = r.resource.environment
    row.host_name = r.resource.host_name

    # Flatten metric data if present
    if r.metric:
        row.metric_name = r.metric.name
        row.metric_value = r.metric.value
        row.metric_unit = r.metric.unit
        row.metric_dimensions = r.metric.dimensions or {}

    # Flatten log data if present
    if r.log:
        row.log_severity = r.log.severity.value
        row.log_message = r.log.message

    row.trace_id = r.trace_id
    row.span_id = r.span_id
    row.raw_payload = r.raw_payload
    row.attributes = r.attributes or {}
    return row


def _row_to_telemetry(row: TelemetryRow) -> TelemetryRecord:
    """
    Translate a SQLAlchemy TelemetryRow into a canonical TelemetryRecord domain entity.

    Args:
        row: ORM row instance from database query.

    Returns:
        Domain entity instance.
    """
    # Reconstruct metric observation if present
    metric: MetricObservation | None = None
    if row.metric_name is not None and row.metric_value is not None:
        metric = MetricObservation(
            name=row.metric_name,
            value=row.metric_value,
            unit=row.metric_unit,
            dimensions=row.metric_dimensions or {},
        )

    # Reconstruct log record if present
    log_record: LogRecord | None = None
    if row.log_message is not None:
        log_record = LogRecord(
            severity=Severity(row.log_severity or "info"),
            message=row.log_message,
        )

    # Reconstruct top-level TelemetryRecord
    return TelemetryRecord(
        event_id=row.event_id,
        timestamp=row.timestamp,
        signal_type=SignalType(row.signal_type),
        source=TelemetrySource(
            provider=row.provider,
            integration_id=row.integration_id,
        ),
        resource=ResourceIdentity(
            service_name=row.service_name,
            service_namespace=row.service_namespace,
            service_version=row.service_version,
            environment=row.environment,
            host_name=row.host_name,
        ),
        metric=metric,
        log=log_record,
        trace_id=row.trace_id,
        span_id=row.span_id,
        raw_payload=row.raw_payload,
        attributes=row.attributes or {},
    )


def _incident_to_dict(i: Incident) -> dict[str, Any]:
    """
    Convert a canonical Incident domain entity into a column dictionary for ORM insert.

    Args:
        i: Domain Incident instance.

    Returns:
        Dictionary of column values.
    """
    return {
        "incident_id": i.incident_id,
        "created_at": i.created_at,
        "updated_at": i.updated_at,
        "severity": i.severity.value,
        "status": i.status.value,
        "service_name": i.service_name,
        "service_namespace": i.service_namespace,
        "environment": i.environment,
        "trigger_type": i.trigger_type.value,
        "trigger_rule_id": i.trigger_rule_id,
        "trigger_rule_name": i.trigger_rule_name,
        "title": i.title,
        "description": i.description,
        "source_provider": i.source_provider,
        "source_integration_id": i.source_integration_id,
        "episode_key": i.episode_key,
        "initial_evidence": [e.model_dump(mode="json") for e in i.initial_evidence],
        "context": i.context,
    }


def _row_to_incident(row: IncidentRow) -> Incident:
    """
    Convert a SQLAlchemy IncidentRow into a canonical Incident domain entity.

    Args:
        row: ORM IncidentRow model instance.

    Returns:
        Domain Incident entity instance.
    """
    evidence_raw: list[dict[str, Any]] = row.initial_evidence or []
    evidence = [EvidenceItem(**e) for e in evidence_raw]

    return Incident(
        incident_id=row.incident_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        severity=IncidentSeverity(row.severity),
        status=IncidentStatus(row.status),
        service_name=row.service_name,
        service_namespace=row.service_namespace,
        environment=row.environment,
        trigger_type=TriggerType(row.trigger_type),
        trigger_rule_id=row.trigger_rule_id,
        trigger_rule_name=row.trigger_rule_name,
        title=row.title,
        description=row.description,
        source_provider=row.source_provider,
        source_integration_id=row.source_integration_id,
        episode_key=row.episode_key,
        initial_evidence=evidence,
        context=row.context or {},
    )


def _investigation_to_dict(res: InvestigationResult) -> dict[str, Any]:
    """
    Convert an InvestigationResult domain entity to a dict for ORM insert/update.

    Uses Pydantic model_dump(mode="json") to ensure datetime and enums are JSON-safe.
    """
    return {
        "incident_id": res.incident_id,
        "status": res.status.value,
        "confidence": res.confidence,
        "diagnosis": res.diagnosis.model_dump(mode="json") if res.diagnosis else None,
        "supporting_evidence": [e.model_dump(mode="json") for e in res.supporting_evidence],
        "investigation_steps": [s.model_dump(mode="json") for s in res.investigation_steps],
        "tool_calls_summary": res.tool_calls_summary,
        "duration_seconds": res.duration_seconds,
        "iteration_count": res.iteration_count,
        "failure_reason": res.failure_reason,
        "completed_at": res.completed_at,
    }


def _row_to_investigation(row: InvestigationRow) -> InvestigationResult:
    """
    Convert a SQLAlchemy InvestigationRow to a canonical InvestigationResult domain entity.
    """
    diagnosis = Diagnosis(**row.diagnosis) if row.diagnosis else None
    evidence = [InvestigationEvidence(**e) for e in (row.supporting_evidence or [])]
    steps = [InvestigationStep(**s) for s in (row.investigation_steps or [])]

    return InvestigationResult(
        incident_id=row.incident_id,
        status=InvestigationStatus(row.status),
        diagnosis=diagnosis,
        confidence=row.confidence,
        supporting_evidence=evidence,
        investigation_steps=steps,
        tool_calls_summary=row.tool_calls_summary or [],
        duration_seconds=row.duration_seconds,
        iteration_count=row.iteration_count,
        failure_reason=row.failure_reason,
        completed_at=row.completed_at,
    )

