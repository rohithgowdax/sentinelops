"""
Labeled Knowledge Retrieval Benchmark Dataset for SentinelOps.

Defines 50 operational benchmark queries with ground-truth relevant document IDs
and chunk identifiers for evaluating Recall@k, MRR, and nDCG@k across retrieval modes:
- dense_only
- sparse_only
- hybrid (RRF)
- hybrid_plus_rerank
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from sentinelops.domain.models.knowledge import DocumentType


class LabeledRetrievalQuery(BaseModel):
    """
    A single evaluation query with annotated relevance labels.
    """

    query_id: str
    query: str
    expected_document_ids: list[str]
    expected_chunks: list[str] = Field(default_factory=list)
    service_filter: str | None = None
    document_type_filter: DocumentType | None = None
    category: str = "general"


RETRIEVAL_BENCHMARK_QUERIES: list[LabeledRetrievalQuery] = [
    # ── Database & Resource Exhaustion (10 queries) ───────────────────────────
    LabeledRetrievalQuery(
        query_id="Q01",
        query="PostgreSQL remaining connection slots reserved for non-replication superuser connections",
        expected_document_ids=["rb-db-001", "pm-2026-02"],
        category="database",
    ),
    LabeledRetrievalQuery(
        query_id="Q02",
        query="active connections hitting maximum pool size on payments service database",
        expected_document_ids=["rb-db-001", "arch-001"],
        service_filter="payments-service",
        category="database",
    ),
    LabeledRetrievalQuery(
        query_id="Q03",
        query="database connection pool exhaustion troubleshooting steps",
        expected_document_ids=["rb-db-001"],
        category="database",
    ),
    LabeledRetrievalQuery(
        query_id="Q04",
        query="checkout webhook unclosed SQLAlchemy session causing connection leak",
        expected_document_ids=["pm-2026-02", "rb-db-001"],
        category="database",
    ),
    LabeledRetrievalQuery(
        query_id="Q05",
        query="PostgreSQL database cluster max connections limit and superuser reserved",
        expected_document_ids=["arch-003", "rb-db-001"],
        category="database",
    ),
    LabeledRetrievalQuery(
        query_id="Q06",
        query="database IOPS burst balance 0 percent disk latency spike",
        expected_document_ids=["rb-disk-009"],
        category="database",
    ),
    LabeledRetrievalQuery(
        query_id="Q07",
        query="gp3 volume provisioned IOPS saturation on database instance",
        expected_document_ids=["rb-disk-009"],
        category="database",
    ),
    LabeledRetrievalQuery(
        query_id="Q08",
        query="automated failover rules when primary database node heartbeat lost",
        expected_document_ids=["policy-002", "arch-003"],
        category="database",
    ),
    LabeledRetrievalQuery(
        query_id="Q09",
        query="long running active transactions blocking connection slots query",
        expected_document_ids=["rb-db-001"],
        category="database",
    ),
    LabeledRetrievalQuery(
        query_id="Q10",
        query="database topology patroni etcd primary standby replication",
        expected_document_ids=["arch-003"],
        category="database",
    ),

    # ── Memory Leaks & Compute/JVM (8 queries) ────────────────────────────────
    LabeledRetrievalQuery(
        query_id="Q11",
        query="container OOMKilled exit code 137 monotonic memory climb",
        expected_document_ids=["rb-svc-002"],
        category="memory",
    ),
    LabeledRetrievalQuery(
        query_id="Q12",
        query="payments-service heap exhaustion unclosed streaming responses",
        expected_document_ids=["rb-svc-002"],
        service_filter="payments-service",
        category="memory",
    ),
    LabeledRetrievalQuery(
        query_id="Q13",
        query="JVM Stop-the-world garbage collection pause exceeding 2000ms",
        expected_document_ids=["rb-jvm-010", "pm-2026-06"],
        category="memory",
    ),
    LabeledRetrievalQuery(
        query_id="Q14",
        query="G1GC tuning MaxGCPauseMillis and young generation size",
        expected_document_ids=["rb-jvm-010"],
        category="memory",
    ),
    LabeledRetrievalQuery(
        query_id="Q15",
        query="cgroup memory limit reached rolling restart deployment mitigation",
        expected_document_ids=["rb-svc-002"],
        category="memory",
    ),
    LabeledRetrievalQuery(
        query_id="Q16",
        query="unbounded dictionary cache memory growth in python service",
        expected_document_ids=["rb-svc-002"],
        category="memory",
    ),
    LabeledRetrievalQuery(
        query_id="Q17",
        query="local in-memory LRU cache L1 tier architecture and invalidation",
        expected_document_ids=["arch-005", "rb-svc-002"],
        category="memory",
    ),
    LabeledRetrievalQuery(
        query_id="Q18",
        query="analytics service container restart due to memory saturation",
        expected_document_ids=["rb-svc-002", "rb-jvm-010"],
        category="memory",
    ),

    # ── Dependencies & Network / Gateways (10 queries) ────────────────────────
    LabeledRetrievalQuery(
        query_id="Q19",
        query="AcmePay external payment gateway latency spike and timeout cascade",
        expected_document_ids=["rb-dep-003", "pm-2026-01"],
        category="dependency",
    ),
    LabeledRetrievalQuery(
        query_id="Q20",
        query="payments-service client http timeout 30s causing worker pool starvation",
        expected_document_ids=["pm-2026-01", "rb-dep-003"],
        service_filter="payments-service",
        category="dependency",
    ),
    LabeledRetrievalQuery(
        query_id="Q21",
        query="circuit breaker trip events to third-party payment provider fallback",
        expected_document_ids=["rb-dep-003", "arch-001"],
        category="dependency",
    ),
    LabeledRetrievalQuery(
        query_id="Q22",
        query="ingress controller 502 bad gateway upstream connection reset",
        expected_document_ids=["rb-net-008"],
        category="network",
    ),
    LabeledRetrievalQuery(
        query_id="Q23",
        query="keepalive timeout mismatch between ingress envoy and upstream service",
        expected_document_ids=["rb-net-008"],
        category="network",
    ),
    LabeledRetrievalQuery(
        query_id="Q24",
        query="intermittent DNS resolution failure CoreDNS conntrack table exhaustion",
        expected_document_ids=["pm-2026-07"],
        category="network",
    ),
    LabeledRetrievalQuery(
        query_id="Q25",
        query="NodeLocal DNSCache daemonset deployment and nf_conntrack sysctl",
        expected_document_ids=["pm-2026-07"],
        category="network",
    ),
    LabeledRetrievalQuery(
        query_id="Q26",
        query="payments service architecture external dependencies AcmePay p95",
        expected_document_ids=["arch-001", "rb-dep-003"],
        category="dependency",
    ),
    LabeledRetrievalQuery(
        query_id="Q27",
        query="third party partner degradation incident INC-2026-01 postmortem",
        expected_document_ids=["pm-2026-01"],
        category="dependency",
    ),
    LabeledRetrievalQuery(
        query_id="Q28",
        query="HTTP client timeout configuration recommendation for external APIs",
        expected_document_ids=["pm-2026-01", "rb-dep-003"],
        category="dependency",
    ),

    # ── Deployments & Regressions (8 queries) ──────────────────────────────────
    LabeledRetrievalQuery(
        query_id="Q29",
        query="canary deployment error rate spike immediate rollback procedure",
        expected_document_ids=["rb-deploy-005"],
        category="deployment",
    ),
    LabeledRetrievalQuery(
        query_id="Q30",
        query="Release v2.4.0 database migration merchant_account_id regression incident",
        expected_document_ids=["pm-2026-04", "rel-001"],
        category="deployment",
    ),
    LabeledRetrievalQuery(
        query_id="Q31",
        query="revert to previous stable image tag v2.3.9 error rate baseline",
        expected_document_ids=["rb-deploy-005", "pm-2026-04", "rel-004"],
        category="deployment",
    ),
    LabeledRetrievalQuery(
        query_id="Q32",
        query="release notes v2.4.0 multi-currency checkout hotfix regression",
        expected_document_ids=["rel-001", "pm-2026-04"],
        category="deployment",
    ),
    LabeledRetrievalQuery(
        query_id="Q33",
        query="stable production baseline release notes v2.3.9 payments service",
        expected_document_ids=["rel-004"],
        category="deployment",
    ),
    LabeledRetrievalQuery(
        query_id="Q34",
        query="Friday afternoon change freeze deployment governance policy",
        expected_document_ids=["policy-001"],
        category="policy",
    ),
    LabeledRetrievalQuery(
        query_id="Q35",
        query="emergency hotfix approval requirements during holiday freeze",
        expected_document_ids=["policy-001"],
        category="policy",
    ),
    LabeledRetrievalQuery(
        query_id="Q36",
        query="SEV-1 and SEV-2 incident classification and response SLA matrix",
        expected_document_ids=["policy-004"],
        category="policy",
    ),

    # ── Queues, Caching & Auth (8 queries) ────────────────────────────────────
    LabeledRetrievalQuery(
        query_id="Q37",
        query="Redis cache eviction surge and database cache stampede",
        expected_document_ids=["rb-cache-006", "pm-2026-03"],
        category="cache",
    ),
    LabeledRetrievalQuery(
        query_id="Q38",
        query="missing key TTL causing Redis out of memory eviction storm",
        expected_document_ids=["pm-2026-03", "rb-cache-006"],
        category="cache",
    ),
    LabeledRetrievalQuery(
        query_id="Q39",
        query="Redis memory volatile-lru allkeys-lru eviction policy configuration",
        expected_document_ids=["rb-cache-006", "arch-005"],
        category="cache",
    ),
    LabeledRetrievalQuery(
        query_id="Q40",
        query="consumer lag exceeds 50000 messages on order service queue",
        expected_document_ids=["rb-queue-004"],
        category="queue",
    ),
    LabeledRetrievalQuery(
        query_id="Q41",
        query="Kafka consumer group rebalance storm max.poll.interval.ms GC pause",
        expected_document_ids=["pm-2026-06", "rb-queue-004"],
        category="queue",
    ),
    LabeledRetrievalQuery(
        query_id="Q42",
        query="poison pill message dead letter queue routing procedure",
        expected_document_ids=["rb-queue-004"],
        category="queue",
    ),
    LabeledRetrievalQuery(
        query_id="Q43",
        query="JWT RS256 signing key rotation and JWKS cache propagation failure",
        expected_document_ids=["pm-2026-05", "rb-auth-007"],
        category="auth",
    ),
    LabeledRetrievalQuery(
        query_id="Q44",
        query="401 unauthorized spike edge verification key mismatch auth service",
        expected_document_ids=["pm-2026-05", "rb-auth-007", "arch-002"],
        category="auth",
    ),

    # ── Platform Architecture & Policies (6 queries) ──────────────────────────
    LabeledRetrievalQuery(
        query_id="Q45",
        query="message broker topology Redis Streams for SentinelOps Kafka for audit",
        expected_document_ids=["arch-004"],
        category="architecture",
    ),
    LabeledRetrievalQuery(
        query_id="Q46",
        query="operational telemetry records PostgreSQL retention 30 days cold storage",
        expected_document_ids=["policy-003"],
        category="policy",
    ),
    LabeledRetrievalQuery(
        query_id="Q47",
        query="incident investigation records 365 days compliance audit retention",
        expected_document_ids=["policy-003"],
        category="policy",
    ),
    LabeledRetrievalQuery(
        query_id="Q48",
        query="cross-region traffic failover two authorized on-call engineers requirement",
        expected_document_ids=["policy-002"],
        category="policy",
    ),
    LabeledRetrievalQuery(
        query_id="Q49",
        query="global authentication architecture Envoy edge JWT verification",
        expected_document_ids=["arch-002"],
        category="architecture",
    ),
    LabeledRetrievalQuery(
        query_id="Q50",
        query="two-tier caching architecture L1 local LRU and L2 Redis cluster",
        expected_document_ids=["arch-005"],
        category="architecture",
    ),
]
