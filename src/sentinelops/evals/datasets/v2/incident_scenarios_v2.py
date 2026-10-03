"""
Benchmark v2: Harder and More Realistic Operational Incident Scenarios for SentinelOps.

Defines 60 held-out incidents across 10 specialized failure/reasoning categories (6 scenarios per category):
A. Stale documentation (telemetry reflects v2 behavior; runbook describes v1)
B. Conflicting runbooks (two documents provide conflicting guidance)
C. Lexically similar distractors (almost identical error terms for different services)
D. Missing documentation (root cause not documented; agent must rely on telemetry and report uncertainty)
E. Version-specific failure (version diff introduces regression)
F. Multiple plausible hypotheses (at least two plausible hypotheses; evidence distinguishes)
G. Contradictory telemetry (telemetry signals disagree; confidence must be moderated)
H. Irrelevant highly-ranked knowledge (high lexical overlap with irrelevant docs)
I. Stale postmortem (historical incident occurred under different architecture)
J. Multi-source causal chain (deployment + metric + log + dependency causal chain)

Ground truth isolation:
- Ground-truth root causes and metadata are stored ONLY in evaluator scenario structures.
- Ground truth is strictly prohibited from leaking into `incident.title`, `incident.description`,
  prompts, agent state, or tool outputs.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from sentinelops.domain.models.incident import (
    EvidenceItem,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    TriggerType,
)


class GroundTruthScenarioMetadata(BaseModel):
    """
    Authoritative evaluation metadata owned strictly by the evaluation harness.
    NEVER passed to the agent, prompts, or incident context.
    """

    incident_id: str
    scenario_class: str
    expected_root_cause: str
    acceptable_root_causes: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    expected_uncertainty: str = "low"  # "low", "medium", "high", "insufficient_evidence"
    knowledge_documents_that_should_help: list[str] = Field(default_factory=list)
    distractor_documents: list[str] = Field(default_factory=list)
    forbidden_ground_truth_leakage: list[str] = Field(default_factory=list)


class IncidentScenarioV2(BaseModel):
    """
    A single held-out v2 benchmark scenario combining agent-visible incident data
    with strictly isolated ground truth metadata.
    """

    scenario_id: str
    category_code: str  # A..J
    scenario_class: str
    incident: Incident
    ground_truth: GroundTruthScenarioMetadata
    simulated_telemetry: dict[str, Any]

    # Backward-compatible properties for evaluators
    @property
    def expected_root_cause_concept(self) -> str:
        return self.ground_truth.expected_root_cause

    @property
    def category(self) -> str:
        return self.scenario_class


def _create_v2_scenario(
    scenario_id: str,
    category_code: str,
    scenario_class: str,
    service: str,
    rule_id: str,
    rule_name: str,
    metric_name: str,
    metric_val: float,
    threshold: float,
    expected_rc: str,
    acceptable_rcs: list[str],
    req_ev: list[str],
    contra_ev: list[str],
    uncertainty: str,
    helpful_docs: list[str],
    distractors: list[str],
    forbidden: list[str],
    baseline_val: float = 0.05,
) -> IncidentScenarioV2:
    inc_id = f"INC-V2-{scenario_id}"
    now = datetime.now(tz=timezone.utc)

    # Agent-visible incident: MUST NOT contain expected_rc or forbidden leakage
    incident = Incident(
        incident_id=inc_id,
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
        description=f"Automated alert: {metric_name} observed at {metric_val:.3f}, exceeding threshold {threshold:.3f}",
        source_provider="otel",
        source_integration_id="otel-collector-prod",
        episode_key=f"{rule_id}::{service}::production",
        initial_evidence=[
            EvidenceItem(
                kind="metric",
                description=f"Observed {metric_name} = {metric_val:.3f}",
                value=metric_val,
                attributes={"metric_name": metric_name, "threshold": threshold},
            )
        ],
    )

    ground_truth = GroundTruthScenarioMetadata(
        incident_id=inc_id,
        scenario_class=scenario_class,
        expected_root_cause=expected_rc,
        acceptable_root_causes=acceptable_rcs,
        required_evidence=req_ev,
        contradicting_evidence=contra_ev,
        expected_uncertainty=uncertainty,
        knowledge_documents_that_should_help=helpful_docs,
        distractor_documents=distractors,
        forbidden_ground_truth_leakage=forbidden,
    )

    simulated_telemetry = {
        "recent": {
            "resource": service,
            "metric": metric_name,
            "sample_count": 12,
            "observed_avg": metric_val,
            "observed_max": metric_val * 1.2,
            "observed_min": metric_val * 0.8,
            "latest_value": metric_val,
            "raw_references": [f"event-{scenario_id}-01", f"event-{scenario_id}-02"],
        },
        "baseline": {
            "resource": service,
            "metric": metric_name,
            "sample_count": 30,
            "baseline_avg": baseline_val,
            "baseline_stddev": baseline_val * 0.15,
            "elevation_ratio": round(metric_val / max(baseline_val, 0.001), 2),
        },
    }

    return IncidentScenarioV2(
        scenario_id=scenario_id,
        category_code=category_code,
        scenario_class=scenario_class,
        incident=incident,
        ground_truth=ground_truth,
        simulated_telemetry=simulated_telemetry,
    )


def build_benchmark_v2_scenarios() -> list[IncidentScenarioV2]:
    scenarios: list[IncidentScenarioV2] = []

    # Category A: Stale documentation (6 scenarios)
    # Telemetry indicates v2 async pooling behavior; v1 runbook describes synchronous threadpool
    for i in range(1, 7):
        sid = f"STALE-{i:02d}"
        scenarios.append(
            _create_v2_scenario(
                scenario_id=sid,
                category_code="A",
                scenario_class="stale_documentation",
                service="payments-service" if i % 2 == 1 else "order-service",
                rule_id=f"rule-stale-{i:02d}",
                rule_name="Database Connection Saturation",
                metric_name="db.pool.exhaustion_rate",
                metric_val=0.45 + (i * 0.05),
                threshold=0.20,
                expected_rc="async connection pool leak in v2 client",
                acceptable_rcs=["connection pool leak", "async session leak", "v2 connection exhaustion"],
                req_ev=["metric", "release"],
                contra_ev=["v1 threadpool exhaustion"],
                uncertainty="medium",
                helpful_docs=["rel-003", "pm-2026-02"],
                distractors=["rb-db-001"],  # rb-db-001 has stale v1 recommendations
                forbidden=["stale v1 threadpool", "ignore v2 async"],
            )
        )

    # Category B: Conflicting runbooks (6 scenarios)
    # Two runbooks suggest conflicting actions: rollback deployment vs increase cache capacity
    for i in range(1, 7):
        sid = f"CONF-{i:02d}"
        scenarios.append(
            _create_v2_scenario(
                scenario_id=sid,
                category_code="B",
                scenario_class="conflicting_runbooks",
                service="checkout-service" if i % 2 == 1 else "inventory-service",
                rule_id=f"rule-conf-{i:02d}",
                rule_name="Elevated API Latency",
                metric_name="http.server.duration_p99",
                metric_val=2.8 + (i * 0.3),
                threshold=1.5,
                expected_rc="unindexed query regression requiring rollback",
                acceptable_rcs=["query regression", "deployment rollback needed", "missing database index"],
                req_ev=["metric", "release", "log"],
                contra_ev=["cache size increase alone fixes query regression"],
                uncertainty="medium",
                helpful_docs=["rb-deploy-005", "pm-2026-04"],
                distractors=["rb-cache-006"],
                forbidden=["conflicting instructions", "arbitrary choice"],
            )
        )

    # Category C: Lexically similar distractors (6 scenarios)
    # Similar error phrases across services: Redis eviction on auth vs Kafka buffer on payments
    for i in range(1, 7):
        sid = f"LEX-{i:02d}"
        scenarios.append(
            _create_v2_scenario(
                scenario_id=sid,
                category_code="C",
                scenario_class="lexically_similar_distractors",
                service="auth-service" if i % 2 == 1 else "notification-service",
                rule_id=f"rule-lex-{i:02d}",
                rule_name="Eviction Rate Spike",
                metric_name="cache.eviction_rate",
                metric_val=1500.0 + (i * 200),
                threshold=500.0,
                expected_rc="redis maxmemory policy key eviction",
                acceptable_rcs=["redis eviction", "cache memory exhaustion", "session store eviction"],
                req_ev=["metric", "runbook"],
                contra_ev=["kafka queue backlog", "postgres connection pool"],
                uncertainty="low",
                helpful_docs=["rb-cache-006", "pm-2026-03"],
                distractors=["rb-queue-004", "rb-db-001"],
                forbidden=["kafka distractor", "wrong service match"],
                baseline_val=50.0,
            )
        )

    # Category D: Missing documentation (6 scenarios)
    # Novel bug with zero runbooks; agent must diagnose via telemetry and flag uncertainty
    for i in range(1, 7):
        sid = f"MISS-{i:02d}"
        scenarios.append(
            _create_v2_scenario(
                scenario_id=sid,
                category_code="D",
                scenario_class="missing_documentation",
                service="analytics-pipeline" if i % 2 == 1 else "billing-cron",
                rule_id=f"rule-miss-{i:02d}",
                rule_name="Kernel Network Buffer Drop",
                metric_name="net.socket.udp_drops",
                metric_val=850.0 + (i * 100),
                threshold=100.0,
                expected_rc="undocumented kernel socket buffer exhaustion",
                acceptable_rcs=["socket buffer drop", "network buffer exhaustion", "undocumented kernel drop"],
                req_ev=["metric"],
                contra_ev=[],
                uncertainty="insufficient_evidence",
                helpful_docs=[],
                distractors=["rb-net-008", "pm-2026-07"],
                forbidden=["fabricate runbook", "hallucinate documented fix"],
                baseline_val=5.0,
            )
        )

    # Category E: Version-specific failure (6 scenarios)
    # Symptoms match generic timeout, but root cause is a regression in v2.4.0 release notes
    for i in range(1, 7):
        sid = f"VER-{i:02d}"
        scenarios.append(
            _create_v2_scenario(
                scenario_id=sid,
                category_code="E",
                scenario_class="version_specific_failure",
                service="payments-service",
                rule_id=f"rule-ver-{i:02d}",
                rule_name="Payment Gateway Timeout",
                metric_name="payment.gateway.timeout_rate",
                metric_val=0.35 + (i * 0.04),
                threshold=0.10,
                expected_rc="http client connection leak in v2.4.0",
                acceptable_rcs=["v2.4.0 regression", "gateway timeout in v2.4.0", "connection leak in release 2.4.0"],
                req_ev=["metric", "release"],
                contra_ev=["v2.3.9 stable release"],
                uncertainty="low",
                helpful_docs=["rel-003", "pm-2026-01"],
                distractors=["rel-002"],
                forbidden=["v2.3.9 was culprit"],
            )
        )

    # Category F: Multiple plausible hypotheses (6 scenarios)
    # High CPU could be JVM GC pause or unbounded thread execution; GC metrics confirm GC pause
    for i in range(1, 7):
        sid = f"HYP-{i:02d}"
        scenarios.append(
            _create_v2_scenario(
                scenario_id=sid,
                category_code="F",
                scenario_class="multiple_plausible_hypotheses",
                service="order-service" if i % 2 == 1 else "inventory-service",
                rule_id=f"rule-hyp-{i:02d}",
                rule_name="JVM CPU Saturation",
                metric_name="jvm.cpu.utilization",
                metric_val=0.92 + (i * 0.01),
                threshold=0.80,
                expected_rc="concurrent mark-sweep gc pause loop",
                acceptable_rcs=["gc pause", "garbage collection pause", "jvm metaspace gc freeze"],
                req_ev=["metric", "runbook"],
                contra_ev=["infinite while loop in application code"],
                uncertainty="low",
                helpful_docs=["rb-jvm-010"],
                distractors=["rb-deploy-005"],
                forbidden=["unsupported thread leak hypothesis"],
                baseline_val=0.30,
            )
        )

    # Category G: Contradictory telemetry (6 scenarios)
    # Edge proxy reports 502, but service ingress reports 200 OK with keep-alive reset
    for i in range(1, 7):
        sid = f"CONTRA-{i:02d}"
        scenarios.append(
            _create_v2_scenario(
                scenario_id=sid,
                category_code="G",
                scenario_class="contradictory_telemetry",
                service="edge-gateway",
                rule_id=f"rule-contra-{i:02d}",
                rule_name="Edge 502 Bad Gateway Spike",
                metric_name="http.client.502_ratio",
                metric_val=0.28 + (i * 0.03),
                threshold=0.05,
                expected_rc="keepalive timeout race between proxy and upstream",
                acceptable_rcs=["keepalive timeout mismatch", "upstream connection reset", "502 proxy race"],
                req_ev=["metric", "runbook"],
                contra_ev=["upstream crashed"],
                uncertainty="medium",
                helpful_docs=["rb-net-008"],
                distractors=["pm-2026-05"],
                forbidden=["conclude upstream dead"],
            )
        )

    # Category H: Irrelevant highly-ranked knowledge (6 scenarios)
    # Query text heavily matches a deprecated legacy document; agent must reject it
    for i in range(1, 7):
        sid = f"IRREL-{i:02d}"
        scenarios.append(
            _create_v2_scenario(
                scenario_id=sid,
                category_code="H",
                scenario_class="irrelevant_top_knowledge",
                service="user-profile-service",
                rule_id=f"rule-irrel-{i:02d}",
                rule_name="Disk IO Saturation",
                metric_name="disk.io.utilization",
                metric_val=0.95 + (i * 0.008),
                threshold=0.85,
                expected_rc="unbounded debug log rotation writing to root volume",
                acceptable_rcs=["unbounded log file growth", "debug logging disk fill", "log volume saturation"],
                req_ev=["metric", "runbook"],
                contra_ev=["database tablespace exhaustion"],
                uncertainty="low",
                helpful_docs=["rb-disk-009"],
                distractors=["arch-003", "rb-db-001"],
                forbidden=["database storage failure on stateless service"],
                baseline_val=0.25,
            )
        )

    # Category I: Stale postmortem (6 scenarios)
    # Resembles historical postmortem pm-2026-05 (auth token), but current architecture has redis cache
    for i in range(1, 7):
        sid = f"PM-{i:02d}"
        scenarios.append(
            _create_v2_scenario(
                scenario_id=sid,
                category_code="I",
                scenario_class="stale_postmortem",
                service="auth-service",
                rule_id=f"rule-pm-{i:02d}",
                rule_name="Token Verification Failure Cascade",
                metric_name="auth.token.verification_failure_rate",
                metric_val=0.40 + (i * 0.04),
                threshold=0.15,
                expected_rc="jwks public key rotation clock skew",
                acceptable_rcs=["jwks key rotation skew", "public key caching skew", "jwt signature clock drift"],
                req_ev=["metric", "runbook"],
                contra_ev=["token expiry cascade from 2024 architecture"],
                uncertainty="medium",
                helpful_docs=["rb-auth-007"],
                distractors=["pm-2026-05"],
                forbidden=["repeat pm-2026-05 root cause blindly"],
            )
        )

    # Category J: Multi-source causal chain (6 scenarios)
    # Requires linking: Deployment event -> memory elevation -> GC latency -> queue backlog
    for i in range(1, 7):
        sid = f"CHAIN-{i:02d}"
        scenarios.append(
            _create_v2_scenario(
                scenario_id=sid,
                category_code="J",
                scenario_class="multi_source_causal_chain",
                service="order-processor",
                rule_id=f"rule-chain-{i:02d}",
                rule_name="Kafka Consumer Lag Escalation",
                metric_name="kafka.consumer.lag_records",
                metric_val=12000.0 + (i * 1500),
                threshold=2000.0,
                expected_rc="memory leak causing frequent gc pauses stalling kafka consumer commits",
                acceptable_rcs=[
                    "memory leak stalling consumer",
                    "gc pause causing consumer rebalance",
                    "consumer heartbeat timeout due to memory leak",
                ],
                req_ev=["metric", "release", "runbook"],
                contra_ev=["kafka broker failure", "network partition"],
                uncertainty="low",
                helpful_docs=["rb-svc-002", "rb-queue-004", "rel-004"],
                distractors=["pm-2026-06"],
                forbidden=["broker-side outage"],
                baseline_val=50.0,
            )
        )

    return scenarios


INCIDENT_BENCHMARK_SCENARIOS_V2 = build_benchmark_v2_scenarios()


def export_scenarios_to_json(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = [s.model_dump(mode="json") for s in INCIDENT_BENCHMARK_SCENARIOS_V2]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serialized, f, indent=2, default=str)


if __name__ == "__main__":
    out = Path("evals/datasets/v2/scenarios.json")
    export_scenarios_to_json(out)
    print(f"Exported {len(INCIDENT_BENCHMARK_SCENARIOS_V2)} scenarios to {out}")
