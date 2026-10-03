"""
SentinelOps FastAPI REST API Server.

Endpoints Provided:
1. `GET /health`: Liveness probe endpoint returning service status and process uptime.
2. `GET /incidents`: Query paginated list of canonical incidents (`Incident` model).
3. `GET /incidents/{incident_id}`: Retrieve single incident detail by ID.

Design Rule:
- Route handlers contain ZERO business/domain logic.
- Route handlers delegate data retrieval directly to the `OperationalStore` repository.
- OperationalStore lifecycle is managed asynchronously via FastAPI's `lifespan` context manager.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import structlog
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sentinelops.config.settings import get_settings
from sentinelops.domain.models.incident import Incident
from sentinelops.domain.models.investigation import InvestigationResult
from sentinelops.storage.postgres_store import PostgresOperationalStore

# Initialize logger
log = structlog.get_logger(__name__)

# Module-level singletons managed by lifespan context
_store: PostgresOperationalStore | None = None
_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    FastAPI lifespan context manager for startup and shutdown event handling.

    Startup:
    - Loads settings from environment.
    - Instantiates and initializes `PostgresOperationalStore` connection pool.

    Shutdown:
    - Disposes database engine and closes connection pool.
    """
    global _store
    settings = get_settings()

    # Step 1: Initialize OperationalStore repository
    _store = PostgresOperationalStore(dsn=settings.postgres_dsn)
    await _store.initialize()
    log.info("api.started", host=settings.api_host, port=settings.api_port)

    # Hand control over to FastAPI application
    yield

    # Step 2: Shutdown cleanup
    if _store:
        await _store.close()
    log.info("api.stopped")


def create_app() -> FastAPI:
    """
    Application factory function for constructing the FastAPI instance.

    Configures OpenAPI docs, CORS middleware, lifespan handler, and router inclusion.

    Returns:
        FastAPI application instance.
    """
    app = FastAPI(
        title="SentinelOps API",
        description=(
            "AI-native incident intelligence and controlled remediation platform — "
            "POC Slice 1 REST API"
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # Enable Cross-Origin Resource Sharing (CORS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # Register APIRouter endpoints
    app.include_router(router)
    return app


# Instantiate API router
router = APIRouter()


def _get_store() -> PostgresOperationalStore:
    """
    Internal helper retrieving the initialized `PostgresOperationalStore` singleton.

    Raises:
        RuntimeError: If called before lifespan initialization completes.
    """
    if _store is None:
        raise RuntimeError("OperationalStore repository is not initialized.")
    return _store


@router.get("/health", tags=["observability"])
async def health() -> dict[str, Any]:
    """
    Liveness probe endpoint.

    Returns HTTP 200 JSON payload indicating that the FastAPI worker process is running.

    Returns:
        JSON response with status, service identifier, and process uptime in seconds.
    """
    return {
        "status": "ok",
        "service": "sentinelops",
        "uptime_seconds": round(time.time() - _start_time, 1),
    }


@router.get("/incidents", response_model=list[Incident], tags=["incidents"])
async def list_incidents(
    limit: int = Query(
        default=50, ge=1, le=200, description="Maximum number of incidents to return."
    ),
    offset: int = Query(
        default=0, ge=0, description="Number of incidents to skip (pagination offset)."
    ),
) -> list[Incident]:
    """
    List historical canonical incidents ordered by `created_at` DESC.

    Args:
        limit: Max result count (1..200, default: 50).
        offset: Skip count (>= 0, default: 0).

    Returns:
        List of canonical `Incident` Pydantic domain models.
    """
    store = _get_store()
    return await store.list_incidents(limit=limit, offset=offset)


@router.get("/incidents/{incident_id}", response_model=Incident, tags=["incidents"])
async def get_incident(incident_id: str) -> Incident:
    """
    Retrieve details for a specific incident by its unique ID.

    Args:
        incident_id: Formatted incident identifier string (e.g. 'INC-A1B2C3D4').

    Returns:
        Canonical `Incident` domain model.

    Raises:
        HTTPException: 404 NOT FOUND if incident ID is not present in database.
    """
    store = _get_store()
    incident = await store.get_incident(incident_id)
    if incident is None:
        raise HTTPException(
            status_code=404, detail=f"Incident '{incident_id}' not found."
        )
    return incident


@router.get(
    "/incidents/{incident_id}/investigation",
    response_model=InvestigationResult,
    tags=["investigations"],
)
async def get_incident_investigation(incident_id: str) -> InvestigationResult:
    """
    Retrieve AI investigation results for a specific incident.

    Args:
        incident_id: Formatted incident identifier string (e.g. 'INC-A1B2C3D4').

    Returns:
        Canonical `InvestigationResult` domain model.

    Raises:
        HTTPException: 404 NOT FOUND if no investigation exists for this incident ID.
    """
    store = _get_store()
    investigation = await store.get_investigation(incident_id)
    if investigation is None:
        raise HTTPException(
            status_code=404,
            detail=f"Investigation for incident '{incident_id}' not found.",
        )
    return investigation



def main() -> None:
    """Entrypoint function invoked when starting API server via CLI `sentinelops-api`."""
    import uvicorn

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(20),
    )
    settings = get_settings()
    app = create_app()
    # Run uvicorn web server
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
