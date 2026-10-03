"""
SentinelOps Orchestrator Package.

Consumes incident events from Redis stream `sentinel:incidents` and drives the
LangGraph AI investigation loop, persisting durable `InvestigationResult` records.
"""
from sentinelops.orchestrator.service import OrchestratorService

__all__ = ["OrchestratorService"]
