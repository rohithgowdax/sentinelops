"""
SentinelOps Centralized Settings and Environment Configuration.

Uses `pydantic-settings` to manage application configuration.

Configuration Priority:
1. Environment variables prefixed with `SENTINELOPS_` (e.g. `SENTINELOPS_REDIS_URL`).
2. `.env` file key-value pairs.
3. Default fallback values defined in `Settings`.

12-Factor App Compliance:
Zero credentials or host IP addresses are hardcoded in application logic.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application Settings container parsing environment variables and `.env` files.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SENTINELOPS_",  # Automatically maps SENTINELOPS_X -> x
        case_sensitive=False,
        extra="ignore",
    )

    # ── Service Identity Settings ──────────────────────────────────────────────
    service_name: str = Field(
        default="sentinelops", description="Logical service name for structured logs."
    )
    environment: str = Field(
        default="development", description="Deployment environment tag."
    )
    log_level: str = Field(
        default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR)."
    )

    # ── Redis Stream Broker Settings (EventBus) ────────────────────────────────
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection DSN URL.",
    )
    redis_telemetry_stream: str = Field(
        default="sentinel:telemetry",
        description="Redis stream key for telemetry events.",
    )
    redis_incidents_stream: str = Field(
        default="sentinel:incidents",
        description="Redis stream key for incident events.",
    )
    redis_consumer_group: str = Field(
        default="sentinelops-workers",
        description="Consumer group name for workers.",
    )

    # ── PostgreSQL Database Settings (OperationalStore) ────────────────────────
    postgres_dsn: str = Field(
        default="postgresql+asyncpg://sentinelops:sentinelops@localhost:5432/sentinelops",
        description="PostgreSQL asyncpg DSN connection string.",
    )
    postgres_pool_size: int = Field(
        default=5, description="SQLAlchemy async pool size connection limit."
    )

    # ── Detection Engine Settings ──────────────────────────────────────────────
    detection_rules_path: str = Field(
        default="config/detection_rules.yaml",
        description="Path to YAML file containing detection rule definitions.",
    )
    detection_interval_seconds: float = Field(
        default=10.0,
        description="Frequency in seconds at which the detection loop evaluates rules.",
    )

    # ── Ingestion Worker Settings ──────────────────────────────────────────────
    worker_batch_size: int = Field(
        default=20, description="Max message count per Redis XREADGROUP batch."
    )
    worker_block_ms: int = Field(
        default=2000, description="Redis block duration in ms waiting for messages."
    )

    # ── Orchestrator Agent Settings ───────────────────────────────────────────
    orchestrator_consumer_group: str = Field(
        default="sentinelops-orchestrator",
        description="Consumer group name for investigation orchestrator.",
    )
    orchestrator_batch_size: int = Field(
        default=5, description="Max message count per Redis XREADGROUP incident batch."
    )
    orchestrator_block_ms: int = Field(
        default=2000, description="Redis block duration in ms for incident stream."
    )

    # ── Qdrant & Knowledge Base Settings ──────────────────────────────────────
    qdrant_url: str = Field(
        default="http://localhost:6333",
        description="Qdrant vector database URL.",
    )
    qdrant_api_key: str | None = Field(
        default=None,
        description="Optional Qdrant API key for authentication.",
    )
    qdrant_collection: str = Field(
        default="sentinelops_knowledge",
        description="Qdrant collection name for knowledge base.",
    )
    knowledge_dir: str = Field(
        default="knowledge",
        description="Path to knowledge documents directory.",
    )
    retrieval_mode: str = Field(
        default="hybrid",
        description="Default retrieval mode: dense_only, sparse_only, hybrid, hybrid_plus_rerank.",
    )

    # ── LLM Provider Settings ────────────────────────────────────────────────
    llm_provider: str = Field(
        default="deterministic",
        description="Active LLM provider: 'deterministic' or 'real'.",
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="Model identifier for real LLM provider.",
    )
    llm_api_key: str | None = Field(
        default=None,
        description="Optional API key for real LLM provider.",
    )
    llm_base_url: str | None = Field(
        default=None,
        description="Optional base URL for real LLM provider endpoint.",
    )

    # ── API Server Settings ───────────────────────────────────────────────────
    api_host: str = Field(
        default="0.0.0.0", description="Network host interface to bind API server."
    )
    api_port: int = Field(
        default=8000, description="Network port number for API server."
    )



def get_settings() -> Settings:
    """
    Retrieve singleton instance of cached application Settings.

    Returns:
        `Settings` configuration instance.
    """
    return _settings


# Singleton instance loaded once at module import time
_settings = Settings()
