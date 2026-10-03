"""
Held-out Incident Scenarios for SentinelOps Evaluation Benchmark.

Defines 30 realistic, diverse incident scenarios across 5 failure categories:
1. Deployment-related (6)
2. Database / Storage (6)
3. Downstream Dependency (6)
4. Memory / Compute (6)
5. Queue / Cache / Network (6)

Each scenario defines:
- incident attributes (service, rule, severity, metric value)
- simulated telemetry history (samples, baseline vs degraded)
- expected root cause key concept
- expected operational runbook / postmortem document ID
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from sentinelops.domain.models.incident import (
    EvidenceItem,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    TriggerType,
)


class IncidentScenario(BaseModel):
    """
    A single held-out incident scenario for agent evaluation.
    """

    scenario_id: str
    category: str
    incident: Incident
    expected_root_cause_concept: str
    expected_document_id: str
    simulated_telemetry: dict[str, Any]


def _build_scenario(
    scenario_id: str,
    category: str,
    service: str,
    rule_id: str,
    rule_name: str,
    metric_name: str,
    metric_value: float,
    threshold: float,
    expected_concept: str,
    expected_doc_id: str,
    is_elevated: bool = True,
    baseline_val: float = 0.02,
) -> IncidentScenario:
    now = datetime.now(tz=timezone.utc)
    incident = Incident(
        incident_id=f"INC-{scenario_id}",
        created_at=now,
        updated_at=now,
        severity=IncidentSeverity.HIGH,
        service_name=service,
        service_namespace="core",
        environment="production",
        trigger_type=TriggerType.METRIC_THRESHOLD,
        trigger_rule_id=rule_id,
        trigger_rule_name=rule_name,
        title=f"{rule_name} on {service}",
        description=f"Observed {metric_name} value {metric_value} exceeded threshold {threshold}",
        source_provider="otel",
        source_integration_id="otel-prod-agent",
        episode_key=f"{rule_id}::{service}::production",
        initial_evidence=[
            EvidenceItem(
                kind="metric",
                description=f"Observed {metric_name} = {metric_value}",
                value=metric_value,
                attributes={"metric_name": metric_name, "threshold": threshold},
            )
        ],
    )

    simulated_telemetry = {
        "recent": {
            "resource": service,
            "metric": metric_name,
            "sample_count": 10,
            "observed_avg": metric_value,
            "observed_max": metric_value * 1.15,
            "observed_min": metric_value * 0.85,
            "latest_value": metric_value,
            "raw_references": [f"event-{scenario_id}-01", f"event-{scenario_id}-02"],
        },
        "baseline": {
            "resource": service,
            "metric": metric_name,
            "baseline_avg": baseline_val,
            "current_avg": metric_value,
            "elevation_ratio": round(metric_value / max(0.001, baseline_val), 2),
            "is_elevated": is_elevated,
            "baseline_samples": 40,
            "current_samples": 10,
        },
    }

    return IncidentScenario(
        scenario_id=scenario_id,
        category=category,
        incident=incident,
        expected_root_cause_concept=expected_concept,
        expected_document_id=expected_doc_id,
        simulated_telemetry=simulated_telemetry,
    )


INCIDENT_BENCHMARK_SCENARIOS: list[IncidentScenario] = [
    # ── 1. Deployment Regressions (6 scenarios) ───────────────────────────────
    _build_scenario(
        "DEP-01", "deployment", "payments-service",
        "rule-deploy-error-surge", "Post-Deployment Error Surge",
        "http.error_rate", 0.28, 0.10, "regression", "pm-2026-04"
    ),
    _build_scenario(
        "DEP-02", "deployment", "payments-service",
        "rule-canary-failure", "Canary Deployment High Failure Rate",
        "http.error_rate", 0.22, 0.10, "rollback", "rb-deploy-005"
    ),
    _build_scenario(
        "DEP-03", "deployment", "payments-service",
        "rule-v240-mismatch", "Release v2.4.0 Schema Mismatch",
        "http.error_rate", 0.26, 0.10, "v2.4.0", "rel-001"
    ),
    _build_scenario(
        "DEP-04", "deployment", "payments-service",
        "rule-bad-config-release", "Configuration Deploy Rollback Required",
        "http.error_rate", 0.18, 0.10, "rollback", "rb-deploy-005"
    ),
    _build_scenario(
        "DEP-05", "deployment", "order-service",
        "rule-order-v31-regression", "Order Service v3.1.0 Ingestion Spike",
        "http.error_rate", 0.19, 0.10, "regression", "rel-003"
    ),
    _build_scenario(
        "DEP-06", "deployment", "payments-service",
        "rule-post-deploy-5xx", "Sustained Post-Deployment 5xx",
        "http.error_rate", 0.31, 0.10, "rollback", "rb-deploy-005"
    ),

    # ── 2. Database & Resource Exhaustion (6 scenarios) ───────────────────────
    _build_scenario(
        "DB-01", "database", "payments-service",
        "rule-db-pool-exhausted", "PostgreSQL Connection Pool Maxed",
        "http.error_rate", 0.25, 0.10, "connection", "rb-db-001"
    ),
    _build_scenario(
        "DB-02", "database", "payments-service",
        "rule-db-slots-reserved", "Superuser Slots Reserved Error",
        "http.error_rate", 0.29, 0.10, "connection", "pm-2026-02"
    ),
    _build_scenario(
        "DB-03", "database", "payments-service",
        "rule-db-webhook-leak", "Checkout Webhook Connection Leak",
        "http.error_rate", 0.21, 0.10, "connection", "pm-2026-02"
    ),
    _build_scenario(
        "DB-04", "database", "database-cluster",
        "rule-db-iops-saturation", "Storage IOPS Burst Depleted",
        "http.error_rate", 0.24, 0.10, "iops", "rb-disk-009"
    ),
    _build_scenario(
        "DB-05", "database", "payments-service",
        "rule-db-connection-pileup", "Database Transaction Pileup",
        "http.error_rate", 0.19, 0.10, "connection", "rb-db-001"
    ),
    _build_scenario(
        "DB-06", "database", "database-cluster",
        "rule-db-disk-latency", "Storage Latency Exceeded",
        "http.error_rate", 0.22, 0.10, "disk", "rb-disk-009"
    ),

    # ── 3. Downstream Dependency Failures (6 scenarios) ───────────────────────
    _build_scenario(
        "DEPEN-01", "dependency", "payments-service",
        "rule-acmepay-latency", "AcmePay Gateway Latency Degradation",
        "http.error_rate", 0.24, 0.10, "gateway", "pm-2026-01"
    ),
    _build_scenario(
        "DEPEN-02", "dependency", "payments-service",
        "rule-payment-gateway-timeout", "External Payment Gateway Timeout",
        "http.error_rate", 0.27, 0.10, "timeout", "rb-dep-003"
    ),
    _build_scenario(
        "DEPEN-03", "dependency", "payments-service",
        "rule-circuit-breaker-trip", "Circuit Breaker Tripped on Gateway",
        "http.error_rate", 0.20, 0.10, "circuit", "rb-dep-003"
    ),
    _build_scenario(
        "DEPEN-04", "dependency", "payments-service",
        "rule-worker-thread-starvation", "Worker Thread Pool Starvation",
        "http.error_rate", 0.26, 0.10, "timeout", "pm-2026-01"
    ),
    _build_scenario(
        "DEPEN-05", "dependency", "payments-service",
        "rule-partner-api-slowness", "Partner Payment API Degraded",
        "http.error_rate", 0.19, 0.10, "gateway", "rb-dep-003"
    ),
    _build_scenario(
        "DEPEN-06", "dependency", "payments-service",
        "rule-external-rpc-hang", "Downstream RPC Client Hang",
        "http.error_rate", 0.23, 0.10, "timeout", "pm-2026-01"
    ),

    # ── 4. Memory & Compute / JVM (6 scenarios) ───────────────────────────────
    _build_scenario(
        "MEM-01", "memory", "payments-service",
        "rule-container-oom", "Container Memory Limit OOMKilled",
        "http.error_rate", 0.22, 0.10, "memory", "rb-svc-002"
    ),
    _build_scenario(
        "MEM-02", "memory", "payments-service",
        "rule-heap-leak", "Unbounded Heap Cache Leak",
        "http.error_rate", 0.21, 0.10, "memory", "rb-svc-002"
    ),
    _build_scenario(
        "MEM-03", "memory", "analytics-service",
        "rule-jvm-gc-pause", "JVM G1GC Pause Exceeded",
        "http.error_rate", 0.25, 0.10, "gc", "rb-jvm-010"
    ),
    _build_scenario(
        "MEM-04", "memory", "analytics-service",
        "rule-stop-the-world", "Stop The World GC Freeze",
        "http.error_rate", 0.28, 0.10, "gc", "rb-jvm-010"
    ),
    _build_scenario(
        "MEM-05", "memory", "payments-service",
        "rule-memory-cgroup-breach", "CGroup Memory Ceiling Breach",
        "http.error_rate", 0.23, 0.10, "memory", "rb-svc-002"
    ),
    _build_scenario(
        "MEM-06", "memory", "analytics-service",
        "rule-gc-timeout-healthcheck", "Healthcheck Timeout from GC",
        "http.error_rate", 0.20, 0.10, "gc", "rb-jvm-010"
    ),

    # ── 5. Queue, Cache & Network (6 scenarios) ───────────────────────────────
    _build_scenario(
        "NET-01", "queue_cache_net", "shared-cache",
        "rule-redis-eviction-storm", "Redis Memory Eviction Storm",
        "http.error_rate", 0.21, 0.10, "eviction", "pm-2026-03"
    ),
    _build_scenario(
        "NET-02", "queue_cache_net", "shared-cache",
        "rule-cache-stampede", "Cache Miss Database Stampede",
        "http.error_rate", 0.24, 0.10, "cache", "rb-cache-006"
    ),
    _build_scenario(
        "NET-03", "queue_cache_net", "order-service",
        "rule-consumer-lag-spike", "Kafka Consumer Lag Spike",
        "http.error_rate", 0.22, 0.10, "lag", "rb-queue-004"
    ),
    _build_scenario(
        "NET-04", "queue_cache_net", "order-service",
        "rule-kafka-rebalance-storm", "Kafka Consumer Rebalance Storm",
        "http.error_rate", 0.26, 0.10, "rebalance", "pm-2026-06"
    ),
    _build_scenario(
        "NET-05", "queue_cache_net", "api-gateway",
        "rule-ingress-502-bad-gateway", "Ingress 502 Bad Gateway Spike",
        "http.error_rate", 0.25, 0.10, "ingress", "rb-net-008"
    ),
    _build_scenario(
        "NET-06", "queue_cache_net", "platform-dns",
        "rule-dns-conntrack-full", "CoreDNS Conntrack Table Full",
        "http.error_rate", 0.23, 0.10, "dns", "pm-2026-07"
    ),
]
