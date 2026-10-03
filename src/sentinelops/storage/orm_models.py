"""
SQLAlchemy ORM Database Table Schemas for SentinelOps OperationalStore.

Decoupling Notice:
These ORM models (`TelemetryRow`, `IncidentRow`) define the physical database schema
in PostgreSQL. They are completely decoupled from domain logic models (`TelemetryRecord`, `Incident`).
The `PostgresOperationalStore` acts as a repository pattern translating between ORM rows and Domain entities.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative Base class for SQLAlchemy ORM models."""
    pass


class TelemetryRow(Base):
    """
    PostgreSQL database table schema (`telemetry`) for persisted telemetry signals.

    Indexes:
    - `ix_telemetry_service_metric_time`: Compound index on (`service_name`, `metric_name`, `timestamp`).
      Crucial for high-performance time-window lookups by the Detection Engine.
    - `ix_telemetry_timestamp`: Index on `timestamp` for time-based retention cleanups.

    Primary Key:
    - `event_id`: Canonical UUID string. Guarantees idempotent database upserts.
    """

    __tablename__ = "telemetry"

    # Primary key event ID (used for ON CONFLICT DO NOTHING idempotency)
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # Provider and integration metadata
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    integration_id: Mapped[str] = mapped_column(String(128), nullable=False)

    # Service / resource identity fields
    service_name: Mapped[str] = mapped_column(String(256), nullable=False)
    service_namespace: Mapped[str | None] = mapped_column(String(256), nullable=True)
    service_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(64), nullable=True)
    host_name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Flattened metric observation columns
    metric_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    metric_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metric_dimensions: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Flattened log record columns
    log_severity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    log_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Tracing correlation columns
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    span_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Preserved raw payload and extra attributes
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Table Indexing Definitions
    __table_args__ = (
        Index(
            "ix_telemetry_service_metric_time",
            "service_name",
            "metric_name",
            "timestamp",
        ),
        Index("ix_telemetry_timestamp", "timestamp"),
    )


class IncidentRow(Base):
    """
    PostgreSQL database table schema (`incidents`) for canonical operational incidents.

    Indexes:
    - `ix_incidents_episode_key_status`: Compound index on (`episode_key`, `status`).
      Allows ultra-fast active episode deduplication checks during detection loops.
    - `ix_incidents_created_at`: Index on `created_at` for API pagination.

    Primary Key:
    - `incident_id`: Formatted incident ID (e.g. 'INC-A1B2C3D4').
    """

    __tablename__ = "incidents"

    # Primary key incident ID
    incident_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Classification and lifecycle status
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    # Affected service identity
    service_name: Mapped[str] = mapped_column(String(256), nullable=False)
    service_namespace: Mapped[str | None] = mapped_column(String(256), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Rule metadata triggering the incident
    trigger_type: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger_rule_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trigger_rule_name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Generated text descriptions
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Integration metadata
    source_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    source_integration_id: Mapped[str] = mapped_column(String(128), nullable=False)

    # Deduplication episode key ('rule_id::service::env')
    episode_key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)

    # Structured JSON evidence and diagnostic context
    initial_evidence: Mapped[list | None] = mapped_column(JSON, nullable=True)
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Table Indexing Definitions
    __table_args__ = (
        Index("ix_incidents_episode_key_status", "episode_key", "status"),
        Index("ix_incidents_created_at", "created_at"),
    )


class InvestigationRow(Base):
    """
    PostgreSQL database table schema (`investigations`) for persisted AI incident investigations.

    Primary Key:
    - `incident_id`: Canonical incident identifier (one-to-one with Incident in Slice 2).
    """

    __tablename__ = "investigations"

    incident_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    diagnosis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    supporting_evidence: Mapped[list | None] = mapped_column(JSON, nullable=True)
    investigation_steps: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tool_calls_summary: Mapped[list | None] = mapped_column(JSON, nullable=True)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    iteration_count: Mapped[int] = mapped_column(nullable=False, default=1)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_investigations_status", "status"),
        Index("ix_investigations_completed_at", "completed_at"),
    )

