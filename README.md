# SentinelOps

**Provider-Agnostic AI Incident Intelligence and Controlled Remediation for Heterogeneous Production Systems**

---

### Verification & Stability Status

| System Attribute | Verified State | Specification / Standard |
|---|---|---|
| **Test Suite** | ![Tests](https://img.shields.io/badge/tests-236%20passed%20%7C%200%20failed%20%7C%201%20skipped%20%7C%206%20deselected-brightgreen) | Python 3.11+ / Pytest Suite |
| **Safety Invariants** | ![Safety](https://img.shields.io/badge/critical%20safety-12%2F12%20PASS-brightgreen) | Deterministic Policy Boundary (ADR-018, ADR-021) |
| **Interoperability** | ![MCP](https://img.shields.io/badge/MCP-2026--07--28%20spec-blue) | Model Context Protocol JSON-RPC 2.0 |
| **Observability** | ![OTel](https://img.shields.io/badge/OpenTelemetry-W3C%20Trace%20Correlation%20100%25-blue) | W3C `traceparent` Distributed Tracing |
| **License** | ![License](https://img.shields.io/badge/license-MIT-blue) | [MIT License](LICENSE) (Rohith Gowda R) |
| **Architectural Milestone** | ![Status](https://img.shields.io/badge/Slice%201--5-FROZEN-success) ![Status](https://img.shields.io/badge/Slice%206-PARTIAL%20PASS-orange) | Baseline Commit: `d0782ef` |

> **Audit Notice (Slice 6 Milestone Assessment):**  
> SentinelOps Slices 1 through 5 are formally **VERIFIED and FROZEN**. Slice 6 achieved **PARTIAL PASS**: Local MCP over HTTP transport, fault injection, policy safety boundaries, 100% trace correlation, and automated secret/thought redactions are **MEASURED and EMPIRICALLY PASSING**. Live external cloud APIs (External LLM API endpoints and AWS Bedrock AgentCore managed cloud runtime) are unconfigured in this offline environment and are honestly classified as **`NOT RUN`**. SentinelOps does not simulate or fabricate external cloud metrics.

---

## Table of Contents

1. [Executive Summary & Problem Statement](#1-executive-summary--problem-statement)
2. [What SentinelOps Is (and Is Not)](#2-what-sentinelops-is-and-is-not)
3. [Design Principles & Core Invariants](#3-design-principles--core-invariants)
4. [Master System Architecture](#4-master-system-architecture)
5. [Provider-Neutral Abstraction Layer](#5-provider-neutral-abstraction-layer)
6. [Canonical Domain Model](#6-canonical-domain-model)
7. [Event-Driven Trigger & Ingestion Pipeline](#7-event-driven-trigger--ingestion-pipeline)
8. [End-to-End Incident Lifecycle](#8-end-to-end-incident-lifecycle)
9. [LangGraph AI Investigation Topology](#9-langgraph-ai-investigation-topology)
10. [Knowledge Retrieval & RAG Subsystem](#10-knowledge-retrieval--rag-subsystem)
11. [Controlled Remediation & Deterministic Policy Engine](#11-controlled-remediation--deterministic-policy-engine)
12. [Tested Remediation Safety Invariants](#12-tested-remediation-safety-invariants)
13. [Model Context Protocol (MCP) Interoperability](#13-model-context-protocol-mcp-interoperability)
14. [OpenTelemetry Distributed Tracing & Observability](#14-opentelemetry-distributed-tracing--observability)
15. [AWS Bedrock AgentCore Isolation Adapters](#15-aws-bedrock-agentcore-isolation-adapters)
16. [Historical Slice Evolution (Slices 1–6)](#16-historical-slice-evolution-slices-16)
17. [Master Benchmark & Empirical Evaluation Matrix](#17-master-benchmark--empirical-evaluation-matrix)
18. [Security Architecture & Threat Model](#18-security-architecture--threat-model)
19. [Failure Modes & Recovery Procedures](#19-failure-modes--recovery-procedures)
20. [Local Quick Start & Reproducibility Guide](#20-local-quick-start--reproducibility-guide)
21. [Repository Topology & Codebase Map](#21-repository-topology--codebase-map)
22. [Configuration Reference](#22-configuration-reference)
23. [Open-Source Extension Guide](#23-open-source-extension-guide)
24. [Current Limitations & Technical Boundaries](#24-current-limitations--technical-boundaries)
25. [Future Roadmap](#25-future-roadmap)
26. [Technical Glossary](#26-technical-glossary)
27. [Technical Reports Index](#27-technical-reports-index)
28. [License & Copyright](#28-license--copyright)

---

## 1. Executive Summary & Problem Statement

### The Operational Reality
Modern production architectures emit a fragmented deluge of signals: OpenTelemetry spans, proprietary JSON log events, Prometheus timeseries counters, dynamic topology graphs, deployment change markers, and unstructured runbooks. 

When complex production incidents occur, Site Reliability Engineers (SREs) face distinct challenges:
- **Signal Disconnect:** Observability platforms display *what* is failing across dashboards, but cannot synthesize causal links between isolated symptoms (e.g., error rate spikes) and recent state changes (e.g., schema migrations, connection pool saturation).
- **Context Fragmentation:** Knowledge required to diagnose an incident is scattered across incident postmortems, architecture RFCs, and markdown runbooks, disconnected from active telemetry.
- **Uncontrolled Remediation Risks:** Applying automated remediation directly via LLM output is dangerous. Autonomous models suffer from hallucinations, parameter drift, and prompt injection vulnerabilities. Giving an LLM raw API credentials to restart services or roll back deployments risks catastrophic operational failures.

### The SentinelOps Solution
SentinelOps bridges the gap between observability and automated operations without compromising safety:
1. **Provider-Agnostic Telemetry Normalization:** Heterogeneous telemetry formats (OpenTelemetry, custom JSON, cloud-native monitors) are transformed by perimeter adapters into an immutable, canonical domain model.
2. **Deterministic Triggering & Deduplication:** Incidents are created by deterministic rule evaluation and deduplicated by deterministic episode keys over Redis Streams and PostgreSQL.
3. **Structured LangGraph Investigation:** Bounded, stateful investigation workflows query organizational knowledge (via hybrid vector/BM25 retrieval in Qdrant) and telemetry evidence to formulate testable hypotheses and verified diagnoses.
4. **Deterministic Policy Boundary:** Models propose actions via canonical `ActionRequest` objects; **they never execute them directly**. All actions are intercepted by a deterministic `PolicyEngine` enforcing Role-Based Access Control (RBAC), risk classification, cryptographic parameter binding, anti-replay protections, and Human-in-the-Loop (HITL) approval gates.
5. **Post-Action Recovery Verification:** An action is never assumed to have fixed an incident. Post-remediation telemetry is queried against explicit recovery criteria before an incident can be marked resolved.

```text
Heterogeneous Signals ──► Integration Adapters ──► Canonical Domain Model ──► Deterministic Detection
                                                                                       │
                                                                                       ▼
Incident Resolved ◄── Post-Action Verification ◄── Controlled Action ◄── LangGraph Investigation
```

---

## 2. What SentinelOps Is (and Is Not)

To maintain technical clarity and prevent operational misunderstandings, SentinelOps explicitly defines its system boundaries:

### What SentinelOps IS:
- **A Provider-Agnostic Incident Intelligence Engine:** An architectural core that processes telemetry, diagnoses root causes, and manages recovery across heterogeneous environments without vendor lock-in.
- **A Governed Remediation Pipeline:** A deterministic gatekeeper where AI models act strictly as untrusted planners, requiring cryptographic parameter authorization and human sign-off for mutating actions.
- **A Fully Reproducible, Evaluated Framework:** A system backed by 236 passing automated tests, 12 verified safety invariants, paired statistical evaluations, and published benchmarks.
- **An MCP 2026-07-28 Compliant Service:** A system exposing operational telemetry, organizational knowledge, change history, and controlled remediation via standard Model Context Protocol servers.

### What SentinelOps IS NOT:
- **NOT an Unbounded Autonomous Agent:** SentinelOps will never execute shell commands, alter infrastructure, or run remediation scripts without deterministic policy evaluation and authorized actor context.
- **NOT a Proprietary SaaS Platform:** It is an open, portable Python architecture with zero vendor lock-in and zero mandatory cloud dependencies.
- **NOT a Database Replacement:** It does not replace Prometheus, ClickHouse, or Datadog; it consumes normalized streams and queries from them via modular adapters.
- **NOT Universally Immune to Model Failures:** It recognizes that LLMs can hallucinate; hence, it isolates reasoning from authorization, bounds retry loops, and verifies post-action telemetry.

---

## 3. Design Principles & Core Invariants

SentinelOps is built upon twelve engineering principles implemented across the codebase:

| # | Design Principle | Implementation Consequence |
|---|---|---|
| **1** | **Provider Neutrality** | Zero vendor-specific imports or branching (`if provider == ...`) in core domain, detection, or agent ASTs. All vendor mappings are isolated to perimeter adapters. |
| **2** | **Canonical Domain Model** | All subsystems communicate strictly via strongly typed, immutable Pydantic models (`TelemetryRecord`, `Incident`, `ActionRequest`, `Diagnosis`). |
| **3** | **Separation of Reasoning from Authority** | LLM output is data, not authority. A model can emit an `ActionRequest`, but only the deterministic `PolicyEngine` can grant execution rights. |
| **4** | **Evidence-Grounded Investigation** | Diagnoses must cite valid canonical evidence IDs (`evidence_ids`). Hypotheses lacking grounded citations fail verification. |
| **5** | **Explicit Uncertainty & Bounded Loops** | Investigation and remediation loops are strictly bounded by iteration limits (`max_iterations=3`, `max_remediation_attempts=2`) to prevent infinite recursion. |
| **6** | **Human-in-the-Loop (HITL) for Governed Risk** | High-risk actions (`ROLLBACK`, `RESTART`, `SCALE_UP` in production) trigger state graph execution interrupts awaiting cryptographic human approval. |
| **7** | **Post-Action Telemetry Verification** | Provider execution success does not equal incident recovery. The system queries post-action telemetry metrics to verify recovery before closing an incident. |
| **8** | **Event-Driven Orchestration** | Asynchronous decoupled execution via Redis Streams (`sentinel:telemetry`, `sentinel:incidents`) with explicit consumer group ACKs and PEL tracking. |
| **9** | **Observable Execution Workflows** | W3C `traceparent` context propagated through all sync and async boundaries; spans record end-to-end lifecycle timers. |
| **10** | **Fail-Closed Safety Posture** | If a policy rule is ambiguous, an approval token is expired, or a dependency is unreachable, the system fails closed (DENY / HALT). |
| **11** | **Automated Privacy & Data Sanitization** | Sensitive credentials (`[REDACTED_SECRET]`) and internal model thoughts (`[REDACTED_THOUGHT]`) are recursively scrubbed from all exported telemetry. |
| **12** | **Honest Benchmark Classification** | Metrics must be explicitly tagged as `MEASURED`, `SIMULATED`, `NOT RUN`, or `NOT AVAILABLE`. Unconfigured external cloud APIs are never marked as passed. |

---

## 4. Master System Architecture

The SentinelOps architecture enforces strict boundaries between signal ingestion, operational storage, agent reasoning, deterministic policy enforcement, and infrastructure execution.

```mermaid
flowchart TD
    subgraph Signal Ingestion Layer
        EXT_OTEL["OpenTelemetry Source\n(OTel-like JSON)"]
        EXT_CUSTOM["Custom Microservice Logs\n(Proprietary JSON)"]
        ADAPT_OTEL["OtelLikeAdapter"]
        ADAPT_CUSTOM["CustomJsonAdapter"]
        CAN_REC["Canonical TelemetryRecord"]
    end

    subgraph Event Transport & Hot Storage
        REDIS_IN["Redis Stream\n(sentinel:telemetry)"]
        WORKER["Telemetry Ingestion Worker"]
        PG[("PostgreSQL 16\n(OperationalStore)")]
        DET_LOOP["Detection Loop Engine"]
        DEDUP["EpisodeKey Deduplication"]
        REDIS_OUT["Redis Stream\n(sentinel:incidents)"]
    end

    subgraph SentinelOps Core Orchestrator
        ORCH["Incident Orchestrator Runner"]
        LG["LangGraph Investigation StateGraph"]
        QDRANT[("Qdrant Vector DB\n(Knowledge Base)")]
    end

    subgraph Controlled Remediation Boundary
        POL["Deterministic PolicyEngine"]
        HITL{"Policy Gate\n(ALLOW / REQUIRE_APPROVAL / DENY)"}
        APP_SVC["Approval Service\n(Cryptographic Binding)"]
        ACTION_PROV["ActionProvider\n(Mock / Docker / K8s)"]
        VERIFY["Post-Action Telemetry Verifier"]
    end

    subgraph Interoperability & Observability
        MCP["Model Context Protocol Servers\n(HTTP / JSON-RPC 2.0)"]
        OTEL_EXP["OpenTelemetry Tracer\n(W3C Traceparent / Redaction)"]
        AWS_ADAPT["AWS Bedrock AgentCore Adapters\n(Gateway / Runtime)"]
    end

    EXT_OTEL --> ADAPT_OTEL
    EXT_CUSTOM --> ADAPT_CUSTOM
    ADAPT_OTEL --> CAN_REC
    ADAPT_CUSTOM --> CAN_REC
    CAN_REC --> REDIS_IN
    REDIS_IN --> WORKER
    WORKER --> PG
    PG --> DET_LOOP
    DET_LOOP --> DEDUP
    DEDUP --> REDIS_OUT
    REDIS_OUT --> ORCH
    ORCH --> LG
    LG <--> QDRANT
    LG --> POL
    POL --> HITL
    HITL -->|ALLOW| ACTION_PROV
    HITL -->|REQUIRES_APPROVAL| APP_SVC
    APP_SVC -->|Sign-Off Token| ACTION_PROV
    HITL -->|DENY| LG
    ACTION_PROV --> VERIFY
    VERIFY -->|Recovery Telemetry| LG

    LG -.-> MCP
    LG -.-> OTEL_EXP
    MCP -.-> AWS_ADAPT
```

### Concrete POC vs Abstract Production Implementations

| Subsystem | Abstract Architecture Requirement | Concrete POC Implementation | Production Target |
|---|---|---|---|
| **Signal Ingestion** | Pluggable stream ingestion | Ingestion worker consuming Redis Streams | Kafka / AWS Kinesis / OTel Collector |
| **Operational Store** | Time-window relational/timeseries store | PostgreSQL 16 with asyncpg (`OperationalStore`) | TimescaleDB / ClickHouse |
| **Event Transport** | High-throughput ordered pub/sub | Redis Streams 7 with consumer groups | Apache Kafka / AWS SQS-FIFO |
| **Knowledge Store** | Hybrid dense/sparse vector retrieval | Qdrant 1.13.0 with hybrid RRF fusion | Qdrant Cloud / OpenSearch Serverless |
| **Remediation Execution** | Bounded container/orchestration mutator | Mock Container & Deployment Providers | Kubernetes Client / AWS ECS API |
| **Agent Reasoning** | LangGraph StateGraph engine | LangGraph 0.2+ with MemorySaver/PostgresSaver | LangGraph on AgentCore Runtime |
| **Interoperability** | Tool and capability discovery | Local & HTTP JSON-RPC 2.0 (MCP 2026-07-28) | MCP over mTLS / API Gateway |

---

## 5. Provider-Neutral Abstraction Layer

SentinelOps Core contains **zero references** to specific vendor libraries, formats, or SDKs. All operational capabilities are abstracted behind Python `typing.Protocol` interfaces defined in `sentinelops.domain.contracts.protocols`.

```text
External Vendor Payload (OTel / Datadog / Custom)
                       │
                       ▼
          Perimeter Protocol Adapter
                       │
                       ▼
            Canonical Domain Object
                       │
                       ▼
          Provider-Neutral Core Pipeline
```

### Protocol Abstraction Matrix

| Capability | Canonical Contract Interface | Implementation Module | Contract Test File |
|---|---|---|---|
| **Telemetry Ingestion** | `TelemetryAdapter` | `integrations.telemetry.otel_like.adapter`<br>`integrations.telemetry.custom_json.adapter` | `tests/contract/test_generalization.py` |
| **Operational Store** | `OperationalStore` | `storage.postgres_store.PostgresStore` | `tests/integration/test_end_to_end_pipeline.py` |
| **Event Bus** | `EventBus` | `integrations.event_bus.redis_bus.RedisEventBus` | `tests/integration/test_end_to_end_pipeline.py` |
| **Knowledge Retrieval** | `KnowledgeProvider` | `integrations.knowledge.qdrant_provider.QdrantKnowledgeProvider`<br>`integrations.knowledge.in_memory_provider.InMemoryKnowledgeProvider` | `tests/contract/test_knowledge_generalization.py` |
| **Remediation Action** | `ActionProvider` | `integrations.actions.mock_container.MockContainerActionProvider`<br>`integrations.actions.mock_deployment.MockDeploymentActionProvider` | `tests/contract/test_remediation_generalization.py` |
| **LLM Reasoning** | `LLMProvider` | `capabilities.llm.provider.DeterministicLLMProvider`<br>`capabilities.llm.real_provider.RealLLMProvider` | `tests/unit/test_prompt_injection.py` |
| **Telemetry Evidence** | `TelemetryEvidenceProvider` | `capabilities.evidence.telemetry_evidence.TelemetryEvidenceService` | `tests/contract/test_investigation_generalization.py` |

### Generalization Proof & AST Static Audit
To guarantee that provider neutrality cannot be accidentally broken by future contributors, the test suite includes automated Abstract Syntax Tree (AST) inspection:
1. **Zero Provider Branching in Agent Logic:** `tests/contract/test_investigation_generalization.py` parses the AST of every module in `src/sentinelops/agent/` and asserts that no comparison or branching occurs against `provider` or `source_provider`.
2. **Semantic Equivalence Verification:** `tests/contract/test_generalization.py` verifies that when identical system behaviors are represented in OTel JSON vs Custom JSON, both adapters generate canonical records that evaluate to the identical `episode_key` and trigger identical detection outcomes.

---

## 6. Canonical Domain Model

The domain model is the immutable foundation of SentinelOps, implemented as strict Pydantic v2 models in `src/sentinelops/domain/models/`.

```mermaid
erDiagram
    TELEMETRY_RECORD ||--o{ METRIC_OBSERVATION : records
    TELEMETRY_RECORD ||--o{ LOG_RECORD : contains
    INCIDENT ||--o{ EVIDENCE_ITEM : contains
    INCIDENT ||--o{ INVESTIGATION_PLAN : triggers
    INVESTIGATION_PLAN ||--o{ INVESTIGATION_STEP : executes
    INCIDENT ||--o{ HYPOTHESIS : produces
    INCIDENT ||--|| DIAGNOSIS : establishes
    DIAGNOSIS ||--o{ ACTION_REQUEST : proposes
    ACTION_REQUEST ||--|| POLICY_DECISION : receives
    ACTION_REQUEST ||--o| APPROVAL_REQUEST : may_require
    ACTION_REQUEST ||--|| ACTION_RESULT : executes
    ACTION_RESULT ||--|| REMEDIATION_VERIFICATION : verifies
    ACTION_REQUEST ||--o{ AUDIT_EVENT : records
```

### Core Domain Entities

```python
# 1. Canonical Telemetry
class TelemetryRecord(BaseModel):
    event_id: str                      # Unique UUIDv4
    timestamp: datetime                # ISO 8601 UTC
    source: TelemetrySource            # Host, cluster, provider metadata
    resource: ResourceIdentity         # service_name, service_namespace, environment
    signal_type: SignalType            # METRIC, LOG, TRACE, EVENT
    metric: MetricObservation | None   # name, value, unit, dimensions
    log: LogRecord | None              # level, message, attributes
    raw_payload: dict[str, Any]        # Original unparsed payload for auditing

# 2. Canonical Incident
class Incident(BaseModel):
    incident_id: str                   # e.g., "INC-PAYMENTS-20261005-001"
    created_at: datetime
    updated_at: datetime
    severity: IncidentSeverity         # CRITICAL, HIGH, MEDIUM, LOW
    status: IncidentStatus             # OPEN, INVESTIGATING, MITIGATING, RESOLVED, CLOSED
    service_name: str
    service_namespace: str
    environment: str
    title: str
    description: str
    trigger_type: TriggerType          # THRESHOLD, ANOMALY, COMPOSITE, MANUAL
    trigger_rule_id: str
    evidence: list[EvidenceItem]

# 3. Investigation & Diagnosis
class Hypothesis(BaseModel):
    hypothesis_id: str
    statement: str
    supporting_evidence_ids: list[str] # Must cite valid EvidenceItem IDs
    confidence: float                  # Bounded [0.0, 1.0]

class Diagnosis(BaseModel):
    diagnosis_id: str
    incident_id: str
    root_cause: str
    confidence: float
    supporting_evidence_ids: list[str] # Hard citation requirement
    recommended_action_type: ActionType
    recommended_parameters: dict[str, Any]

# 4. Controlled Remediation
class ActionRequest(BaseModel):
    request_id: str                    # Unique UUIDv4
    incident_id: str
    action_type: ActionType            # RESTART, ROLLBACK, SCALE_UP, CONFIG_CHANGE, etc.
    target_resource: TargetResource    # service, namespace, cluster, environment
    parameters: dict[str, Any]         # Action-specific arguments
    actor_context: ActorContext        # actor_id, role, authentication method
    risk_class: RiskClass              # LOW, MEDIUM, HIGH, CRITICAL

class PolicyDecision(BaseModel):
    decision_id: str
    request_id: str
    decision: PolicyDecisionType       # ALLOW, REQUIRES_APPROVAL, DENY
    reason: str
    evaluated_at: datetime
    evaluated_rules: list[str]

class RemediationVerificationResult(BaseModel):
    verification_id: str
    request_id: str
    incident_id: str
    status: RemediationStatus          # RECOVERED, NOT_RECOVERED, DEGRADED
    metric_checks: list[MetricCheckResult]
    observed_at: datetime
```

---

## 7. Event-Driven Trigger & Ingestion Pipeline

SentinelOps decouples signal ingestion from agent investigation using Redis Streams and an asynchronous worker architecture.

```text
External System ──► Adapter ──► [Redis: sentinel:telemetry]
                                            │
                                            ▼
                                   Telemetry Worker
                                     ├──► PostgreSQL (Bulk Insert)
                                     └──► Detection Engine
                                            │ (Threshold / Metric Rules)
                                            ▼
                                  EpisodeKey Deduplication
                                            │
                                            ▼ (incident.created)
                                [Redis: sentinel:incidents]
                                            │
                                            ▼
                               SentinelOps Orchestrator
                                            │
                                            ▼
                                   LangGraph StateGraph
```

### Ingestion Details & Deduplication Invariants
1. **Redis Streams Ingestion:** Raw events are published to `sentinel:telemetry`. The `sentinelops-worker` process consumes batches via `XREADGROUP` within the `sentinelops-workers` consumer group, ensuring at-least-once processing.
2. **Persistence & Windowing:** Normalized `TelemetryRecord` objects are bulk-inserted into PostgreSQL with indexed columns `(service_name, metric_name, timestamp)`.
3. **Deterministic Detection:** The detection engine evaluates declarative YAML rules (e.g., `http.error_rate > 0.10` over 60 seconds).
4. **EpisodeKey Deduplication:** When a rule fires, an `EpisodeKey` is derived:
   ```text
   {rule_id}::{service_name}::{service_namespace}
   ```
   If an open incident already exists with this `episode_key` in the PostgreSQL operational store, duplicate creation is suppressed.
5. **Decoupled Incident Notification:** When a new incident is created, an `incident.created` event is published to `sentinel:incidents`. The `sentinelops-orchestrator` independently consumes this stream to start the LangGraph investigation.

---

## 8. End-to-End Incident Lifecycle

The complete lifecycle transitions from detection through investigation, governance, execution, and verification:

```mermaid
sequenceDiagram
    autonumber
    participant Telemetry as Telemetry Source
    participant Worker as Ingestion Worker
    participant DB as PostgreSQL
    participant Detector as Detection Engine
    participant Bus as Redis Streams
    participant Orch as Orchestrator
    participant Graph as LangGraph Agent
    participant KB as Qdrant Knowledge
    participant Policy as PolicyEngine
    participant Human as Incident Commander
    participant Action as ActionProvider
    participant Verifier as Post-Action Verifier

    Telemetry->>Worker: Ingest raw telemetry
    Worker->>DB: Store canonical TelemetryRecord
    Worker->>Detector: Evaluate detection rules
    Detector->>DB: Query open episode keys
    Detector->>Bus: Publish incident.created (sentinel:incidents)
    Bus->>Orch: Consume incident event
    Orch->>Graph: Initialize StateGraph (thread_id=incident_id)
    Graph->>KB: Retrieve runbooks & postmortems (Hybrid RRF)
    KB-->>Graph: Return top-k relevant knowledge chunks
    Graph->>Graph: Formulate hypothesis & verify citations
    Graph->>Policy: Submit canonical ActionRequest
    alt RiskClass: LOW / Staging
        Policy-->>Graph: PolicyDecision: ALLOW
    else RiskClass: HIGH / Production
        Policy-->>Graph: PolicyDecision: REQUIRES_APPROVAL
        Graph->>Graph: Interrupt execution (AWAIT_APPROVAL)
        Human->>Policy: Submit cryptographic approval token
        Policy-->>Graph: Resume execution with approved token
    else Destructive / Blacklisted Action
        Policy-->>Graph: PolicyDecision: DENY
        Graph->>Graph: Finalize denied & safe halt
    end
    Graph->>Action: Execute authorized action parameters
    Action-->>Graph: ActionResult: SUCCESS
    Graph->>Verifier: Query post-action telemetry (60s window)
    Verifier-->>Graph: VerificationResult: RECOVERED
    Graph->>DB: Update IncidentStatus: RESOLVED
```

---

## 9. LangGraph AI Investigation Topology

SentinelOps orchestrates investigation and remediation as a compiled, cyclic `StateGraph` using LangGraph 0.2+.

```text
                  START
                    │
                    ▼
             incident_intake
                    │
                    ▼
         build_investigation_plan
                    │
                    ▼
    ┌──────► collect_evidence ◄─────────────────────────────────────────────┐
    │               │                                                       │
    │               ▼                                                       │
    │        analyze_evidence                                               │
    │               │                                                       │
    │               ▼                                                       │
    │            diagnose                                                   │
    │               │                                                       │
    │               ▼                                                       │
    │        verify_diagnosis ──────────────────────────────────────────────┤ (Insufficient / Loop back)
    │               │                                                       │
    │               ├── (unverified & max_iterations) ──► finalize ──► END  │
    │               │                                                       │
    │               ▼ (verified)                                            │
    │        plan_remediation                                               │
    │               │                                                       │
    │               ▼                                                       │
    │        evaluate_policy                                                │
    │               │                                                       │
    │               ├── [DENY] ─────────────────────► finalize_denied ──► END
    │               │                                                       │
    │               ├── [REQUIRES_APPROVAL] ──► await_approval (INTERRUPT)  │
    │               │                                 │                     │
    │               │                         [resume with token]           │
    │               │                                 ▼                     │
    │               └── [ALLOW] ──────────────► execute_action              │
    │                                                 │                     │
    │                                                 ▼                     │
    │                                         verify_remediation            │
    │                                            /          \               │
    │                                       RECOVERED    NOT_RECOVERED      │
    │                                           │              │            │
    │                                           ▼              ▼            │
    │                                   finalize_resolved (retry < max) ────┘
    │                                           │              │ (retry >= max)
    │                                           ▼              ▼
    │                                          END      finalize_failed ──► END
```

### Graph Node Specifications

| Node Name | Module Path | Inputs | Outputs | Routing Conditions |
|---|---|---|---|---|
| `incident_intake` | `agent.nodes.intake` | `incident` | Initialized state, intake evidence | Unconditional -> `build_investigation_plan` |
| `build_investigation_plan` | `agent.nodes.planner` | `incident`, evidence | `InvestigationPlan` | Unconditional -> `collect_evidence` |
| `collect_evidence` | `agent.nodes.collector` | Plan steps | Canonical telemetry & knowledge chunks | Unconditional -> `analyze_evidence` |
| `analyze_evidence` | `agent.nodes.analyzer` | Evidence items | Correlated signals & findings | Unconditional -> `diagnose` |
| `diagnose` | `agent.nodes.diagnoser` | Findings | `Diagnosis`, `Hypothesis` list | Unconditional -> `verify_diagnosis` |
| `verify_diagnosis` | `agent.nodes.verifier` | `Diagnosis`, evidence | `VerificationResult` | • Verified -> `plan_remediation`<br>• Unverified (iter < max) -> `collect_evidence`<br>• Unverified (iter >= max) -> `finalize` |
| `plan_remediation` | `agent.nodes.remediation_planner` | `Diagnosis` | Canonical `ActionRequest` | Unconditional -> `evaluate_policy` |
| `evaluate_policy` | `agent.nodes.policy_evaluator` | `ActionRequest` | `PolicyDecision` | • ALLOW -> `execute_action`<br>• REQUIRES_APPROVAL -> `await_approval`<br>• DENY -> `finalize_denied` |
| `await_approval` | `agent.nodes.action_executor` | `ApprovalRequest` | Paused State / Resumed Token | • Approved -> `execute_action`<br>• Rejected / Expired -> `finalize_denied` |
| `execute_action` | `agent.nodes.action_executor` | Approved `ActionRequest` | `ActionResult` | Unconditional -> `verify_remediation` |
| `verify_remediation` | `agent.nodes.remediation_verifier` | `ActionResult`, post-telemetry | `RemediationVerificationResult` | • RECOVERED -> `finalize_resolved`<br>• NOT_RECOVERED (attempts < max) -> `collect_evidence`<br>• NOT_RECOVERED (attempts >= max) -> `finalize_failed` |
| `finalize_resolved` | `agent.nodes.remediation_verifier` | Verified recovery | `InvestigationStatus.RESOLVED` | Terminal -> `END` |
| `finalize_denied` | `agent.nodes.remediation_verifier` | Policy denial reason | `InvestigationStatus.FAILED` | Terminal -> `END` |
| `finalize_failed` | `agent.nodes.remediation_verifier` | Exhausted retries | `InvestigationStatus.FAILED` | Terminal -> `END` |
| `finalize` | `agent.nodes.finalizer` | Unverified investigation | `InvestigationStatus.COMPLETED` | Terminal -> `END` |

### Checkpointing & Interrupt/Resume
State persistence is keyed by `thread_id = incident.incident_id`. When `evaluate_policy` yields `REQUIRES_APPROVAL`, LangGraph interrupts execution. The entire workflow state (evidence, plan, diagnosis, action request) is durably saved in PostgreSQL or MemorySaver. Upon external receipt of a valid human approval token, the orchestrator invokes `graph.invoke(Command(resume=approval_token), config={"configurable": {"thread_id": incident_id}})` to seamlessly resume execution.

---

## 10. Knowledge Retrieval & RAG Subsystem

The SentinelOps retrieval pipeline provides operational context (runbooks, architecture RFCs, postmortems) to the investigation agent.

```text
Markdown Runbooks / Postmortems
               │
               ▼
   Chunking & Semantic Parser
               │
      ┌────────┴────────┐
      ▼                 ▼
Dense Embeddings    Sparse BM25 Index
(384-dim semantic)  (Exact Term Frequencies)
      │                 │
      ▼                 ▼
   Qdrant Dense      InMemory BM25
               │        │
               └────┬───┘
                    ▼
          Reciprocal Rank Fusion
           RRF(d) = Σ 1/(k + rank)
                    │
                    ▼
          Cross-Encoder Reranker
      (Section Boosting & Filtering)
                    │
                    ▼
          Top-K Knowledge Evidence
```

### Storage Isolation Principle
- **Qdrant Vector DB:** Dedicated solely to static and versioned operational knowledge (runbooks, postmortems, service docs).
- **PostgreSQL & Redis:** Dedicated to dynamic, high-velocity operational telemetry and incident state. **Qdrant is never placed on the hot telemetry ingestion path.**

### Retrieval Modes & Algorithms
1. **`dense_only`:** Cosine similarity over normalized 384-dimensional dense vectors.
2. **`sparse_only`:** BM25 term frequency / inverse document frequency scoring over tokenized operational text.
3. **`hybrid`:** Reciprocal Rank Fusion (RRF with constant $k=60$) combining top dense and sparse candidate sets.
4. **`hybrid_plus_rerank`:** Hybrid candidate generation followed by heuristic/cross-encoder section boosting (e.g., boosting `## Remediation` and `## Diagnostic Steps` headers).

### Retrieval Audits & Critical Bug Fixes (Slice 3 Hardening)
During the formal evaluation hardening pass, two mathematical discrepancies were uncovered and permanently corrected:
1. **The BM25 Fit Parity Bug:** Fresh `KnowledgeProvider` instances initially had uninitialized BM25 corpus frequencies, causing sparse scores to collapse to zero and mirror dense output. Fixed by introducing `_ensure_bm25_fit()` to pre-calculate document frequencies across all indexed chunks during startup.
2. **The nDCG DCG Inflation Bug:** Multiple overlapping chunks from the same relevant document previously inflated the Discounted Cumulative Gain ($DCG$). The metric was redesigned to enforce document-level relevance with deduplication, mathematically bounding nDCG strictly to the $[0.0, 1.0]$ interval.

---

## 11. Controlled Remediation & Deterministic Policy Engine

SentinelOps enforces a strict separation: **AI reasoning generates proposals; deterministic code enforces policy.**

```mermaid
flowchart LR
    AGENT["LangGraph Agent\n(Untrusted Reasoner)"]
    REQ["Canonical ActionRequest\n(Parameters, Target, Actor)"]
    ENGINE["Deterministic PolicyEngine\n(Configured Rules)"]
    GATE{"Policy Gate"}
    EXEC["ActionProvider\n(Executes Action)"]
    APPROVAL["Approval Service\n(Awaits Human Sign-Off)"]
    HALT["Safe Halt\n(Audit Recorded)"]

    AGENT -->|Proposes| REQ
    REQ --> ENGINE
    ENGINE --> GATE
    GATE -->|ALLOW| EXEC
    GATE -->|REQUIRES_APPROVAL| APPROVAL
    APPROVAL -->|Approved Token| EXEC
    APPROVAL -->|Rejected / Timeout| HALT
    GATE -->|DENY| HALT
```

### Deterministic Policy Decision Matrix

| Policy Decision | Downstream Action Execution | Approval Required | State Graph Behavior | Audit Consequence |
|---|:---:|:---:|---|---|
| **`ALLOW`** | **YES** | No | Graph transitions directly to `execute_action` | Action recorded with `auto_approved=True` |
| **`REQUIRES_APPROVAL`** | **BLOCKED** | **YES** | Graph executes interrupt, persisting state to checkpointer | `ApprovalRequest` emitted; timer started |
| **`DENY`** | **BLOCKED** | No | Graph transitions to `finalize_denied` -> `END` | Policy violation logged; incident marked failed |

### Cryptographic Parameter Binding & Anti-Replay
1. **Exact-Action Approval Binding:** When human approval is requested for an action, a SHA-256 fingerprint of the normalized request parameters is stored in the `ApprovalRequest`. If an attacker or corrupted model modifies parameters before resumption, fingerprint mismatch triggers immediate denial.
2. **Single-Use Nonce / Anti-Replay:** Approval tokens contain single-use cryptographic nonces. Once an approval is consumed by `execute_action`, its status transitions to `CONSUMED` in PostgreSQL. Replaying an identical approval token is rejected.

---

## 12. Tested Remediation Safety Invariants

The following 12 critical safety invariants are verified by the automated test suite (`tests/security/` and `tests/unit/`):

| Invariant ID | Security Property | Specification & Expected Behavior | Test Status |
|---|---|---|:---:|
| **INV-01** | **Policy Denial Enforcement** | A `DENY` decision guarantees zero downstream provider invocations. | **PASS** |
| **INV-02** | **Mandatory Approval Barrier** | A `REQUIRES_APPROVAL` decision guarantees zero provider calls until a valid token is provided. | **PASS** |
| **INV-03** | **Exact-Action Parameter Binding** | Any parameter modification invalidates the approval token. | **PASS** |
| **INV-04** | **Approval Anti-Replay** | Consumed approval tokens cannot be reused for subsequent action requests. | **PASS** |
| **INV-05** | **RBAC Identity Integrity** | Caller metadata cannot elevate execution privileges without valid credentials. | **PASS** |
| **INV-06** | **Blacklisted Action Rejection** | Destructive actions (e.g., `DELETE_DATABASE`) are unconditionally denied across all environments. | **PASS** |
| **INV-07** | **Schema Enforcement Gate** | Actions violating canonical Pydantic schemas fail before policy evaluation. | **PASS** |
| **INV-08** | **Prompt Injection Resistance** | Adversarial instructions embedded in telemetry or runbooks cannot override policy. | **PASS** |
| **INV-09** | **Automated Secret Redaction** | AWS access keys, bearer tokens, and passwords are recursively scrubbed to `[REDACTED_SECRET]`. | **PASS** |
| **INV-10** | **Internal Thought Redaction** | Model chain-of-thought tokens and scratchpads are scrubbed to `[REDACTED_THOUGHT]`. | **PASS** |
| **INV-11** | **Trace Correlation Integrity** | 100% of execution spans maintain consistent `trace_id` and `incident_id` linkage. | **PASS** |
| **INV-12** | **Bounded Recovery Termination** | Workflows terminate safely within configured limits even when remediation fails. | **PASS** |

> *Note: These are verified invariants within the SentinelOps implementation and test harness. They do not constitute an assertion of universal immunity against unknown zero-day vulnerabilities.*

---

## 13. Model Context Protocol (MCP) Interoperability

SentinelOps implements the **Model Context Protocol (MCP)** specification (revision `2026-07-28`), exposing operational capabilities to external agent frameworks via standard JSON-RPC 2.0 over local process pipes and HTTP.

```text
External AI Agent / Orchestrator (Claude / Cursor / Bedrock)
                              │
                              ▼ JSON-RPC 2.0 (Bearer Auth)
            SentinelOps MCP HTTP Gateway (Port 8000)
                              │
       ┌──────────────────────┼──────────────────────┬──────────────────────┐
       ▼                      ▼                      ▼                      ▼
sentinelops-telemetry  sentinelops-knowledge   sentinelops-change    sentinelops-remediation
(Read-Only Telemetry)   (Read-Only Knowledge)   (Read-Only Changes)   (Safety-Gated Action)
```

### MCP Server Catalog

| Server Name | Exposed Tools | Exposed Resources | Security Classification |
|---|---|---|---|
| **`sentinelops-telemetry`** | • `query_metrics`<br>• `query_logs`<br>• `get_service_health`<br>• `get_dependencies` | `telemetry://service/{service_id}/health` | **READ-ONLY** |
| **`sentinelops-knowledge`** | • `search_knowledge`<br>• `get_document`<br>• `get_evidence` | `knowledge://document/{doc_id}` | **READ-ONLY** |
| **`sentinelops-change`** | • `list_changes`<br>• `get_deployment`<br>• `get_version` | `change://deployment/{service}/{version}` | **READ-ONLY** |
| **`sentinelops-remediation`** | • `propose_action`<br>• `execute_action` | • `incident://remediation/{incident_id}`<br>• `approval://request/{request_id}` | **MUTATING / SAFETY-GATED** |

### MCP Discovery Caching & Protocol Features
- **Stateless Capability Discovery:** Servers emit explicit `CacheHint` directives, allowing clients to cache tool schemas and eliminate discovery round-trips.
- **Stateless Context Propagation:** Inbound requests carry `ProtocolMetadata` (`tenant_id`, `actor_id`, `trace_id`) ensuring end-to-end W3C trace correlation.
- **Perimeter Authentication:** The MCP HTTP transport enforces Bearer token verification; unauthenticated or malformed requests are rejected with HTTP 401 before reaching tool handlers.

---

## 14. OpenTelemetry Distributed Tracing & Observability

SentinelOps provides first-class execution observability into its own internal operations, adhering to W3C Distributed Tracing standards.

### Dual-Role Telemetry Architecture
SentinelOps distinguishes between two distinct classes of telemetry:
1. **Ingested Production Telemetry:** Raw operational signals emitted by external microservices under observation.
2. **Internal Execution Telemetry:** Distributed traces and latency metrics emitted by SentinelOps itself as it investigates and remediates incidents.

### Distributed Tracing & Automated Data Sanitization
Every incident investigation executes within an OpenTelemetry trace context. When child spans are created (e.g., `collector`, `diagnoser`, `policy_evaluator`, `action_executor`), W3C `traceparent` headers are propagated across process and network boundaries.

```text
Span: incident_lifecycle [trace_id: 4bf92f3577b34da6a3ce929d0e0e4736]
 ├── Span: detection_and_intake
 ├── Span: langgraph_investigation
 │    ├── Span: retrieve_knowledge (Qdrant)
 │    └── Span: verify_diagnosis
 ├── Span: evaluate_policy (PolicyEngine)
 ├── Span: execute_remediation (ActionProvider)
 └── Span: post_action_verification
```

#### Recursive Attribute Redaction Engine
To prevent credential leaks or exposure of model reasoning tokens in public observability backends, `sentinelops.observability.tracer` implements recursive attribute sanitization:
- **Sensitive Credentials:** Any attribute matching credential patterns (e.g., `AKIA...`, `Bearer ...`, passwords, tokens) is replaced with `"[REDACTED_SECRET]"`.
- **Internal Scratchpads / Chain-of-Thought:** Model reasoning tokens, intermediate scratchpads, and raw thought logs are scrubbed to `"[REDACTED_THOUGHT]"`.

### Measured End-to-End Lifecycle Timers

| Lifecycle Timer Metric | Description | Target SLA |
|---|---|:---:|
| `time_to_detection` | Duration from first anomalous telemetry timestamp to incident creation | < 15.0 s |
| `time_to_investigation_start` | Delay between `incident.created` event emission and LangGraph intake | < 1.0 s |
| `time_to_diagnosis` | Elapsed time to formulate a verified root cause diagnosis | < 5.0 s |
| `time_to_approval` | Latency awaiting human sign-off (monitored via HITL queue) | Variable |
| `time_to_execution` | Execution latency of authorized `ActionProvider` execution | < 2.0 s |
| `time_to_recovery` | Duration between remediation execution and confirmed metric recovery | < 60.0 s |
| `time_to_resolution` | Total lifecycle duration from detection to final incident resolution | < 90.0 s |

---

## 15. AWS Bedrock AgentCore Isolation Adapters

To support enterprise cloud deployments on AWS Bedrock AgentCore without sacrificing core portability, SentinelOps provides external boundary adapters in `sentinelops.integrations.aws`.

```text
AWS Bedrock AgentCore Ecosystem (Cloud Boundary)
                        │
                        ▼
┌────────────────────────────────────────────────────────┐
│           AWS AgentCore Perimeter Adapters             │
│  ├── AgentCoreGatewayAdapter (SigV4/JWT perimeter auth)│
│  └── AgentCoreRuntimeAdapter (LangGraph execution host)│
└────────────────────────────────────────────────────────┘
                        │
                        ▼ Canonical Invocations (0 AWS SDK Imports)
┌────────────────────────────────────────────────────────┐
│            SentinelOps Provider-Neutral Core           │
└────────────────────────────────────────────────────────┘
```

### Architectural Isolation & Zero-SDK Guarantee
- **Zero AWS SDK Imports in Core:** Static code audits verify that `boto3` and `botocore` are **never imported** in `sentinelops.domain`, `sentinelops.agent`, `sentinelops.detection`, or `sentinelops.policy`.
- **`AgentCoreGatewayAdapter`:** Aggregates SentinelOps MCP servers into an AWS AgentCore Gateway catalog, translating inbound SigV4/JWT credentials into canonical `ActorContext` objects.
- **`AgentCoreRuntimeAdapter`:** Hosts the LangGraph StateGraph on AWS Bedrock AgentCore Runtime, mapping cloud invocations to state graph executions.
- **Current Verification Status:** The adapter logic is fully tested and verified offline (`tests/integration/test_mcp.py`). Live managed cloud execution is unconfigured in this environment and classified as **`NOT RUN`**.

---

## 16. Historical Slice Evolution (Slices 1–6)

SentinelOps was developed through an incremental, contract-verified slice methodology. Each slice expanded capabilities while maintaining backward compatibility:

```mermaid
timeline
    title SentinelOps Architectural Evolution
    Slice 1 (Frozen) : Ingestion & Detection : Canonical models : Redis Streams : 85 Tests Passing
    Slice 2 (Frozen) : AI Investigation : LangGraph StateGraph : Verified diagnosis : 117 Tests Passing
    Slice 3 (Frozen) : Knowledge & RAG : Qdrant hybrid retrieval : Hardened nDCG : 148 Tests Passing
    Slice 4 (Frozen) : Controlled Remediation : Deterministic PolicyEngine : HITL approvals : 204 Tests Passing
    Slice 5 (Frozen) : Interoperability & Observability : MCP 2026-07-28 : W3C OTel tracing : 231 Tests Passing
    Slice 6 (Verified) : Production Validation : HTTP Transport : Fault injection : 236 Tests Passing
```

### Detailed Slice Progression Matrix

| Slice | Architectural Objective | Key Subsystems Introduced | Major Verification & Tests | Key Limitation / Scope Boundary |
|---|---|---|---|---|
| **Slice 1** | Ingestion & Detection Pipeline | `OtelLikeAdapter`, `CustomJsonAdapter`, Redis Streams, PostgreSQL store, Detection Loop | 85 passed; contract equivalence proved across adapters | No AI reasoning; purely deterministic threshold detection |
| **Slice 2** | LangGraph AI Investigation | LangGraph StateGraph, `IncidentIntake`, `Planner`, `Collector`, `Diagnoser`, `Verifier` | 117 passed; AST static check confirmed zero provider branching | No operational knowledge retrieval; no remediation |
| **Slice 3** | Knowledge / RAG & Eval Hardening | Qdrant vector store, BM25 encoder, RRF fusion, Cross-encoder reranker, Benchmark v2 | 148 passed; BM25 fit & nDCG mathematical fixes validated | Reasoning ceiling exposed on adversarial Benchmark v2 (0/60) |
| **Slice 4** | Controlled Remediation & Governance | `ActionRequest`, `PolicyEngine`, `ApprovalService`, `MockActionProviders`, Verifier | 204 passed; 12/12 safety invariants verified | Remediations executed against local mock providers |
| **Slice 5** | Interoperability & Cloud Adapters | 4 MCP servers, OTel distributed tracer, AWS AgentCore Gateway & Runtime adapters | 231 passed; AST confirmed 0 AWS SDK imports in core | MCP tested over in-memory JSON-RPC transports |
| **Slice 6** | Production Validation & Transport | Real MCP over HTTP, Bearer perimeter auth, Fault injection, Trace correlation audit | 236 passed; transport latency measured; 100% trace audit | External Cloud LLM & Live AWS AgentCore classified as NOT RUN |

---

## 17. Master Benchmark & Empirical Evaluation Matrix

Every performance metric reported in SentinelOps is categorized according to strict empirical taxonomy:
- **`MEASURED`:** Empirically verified and executed directly within this repository environment.
- **`SIMULATED`:** Validated using deterministic rule engines, offline emulators, or local mock providers.
- **`NOT RUN`:** Cloud-dependent capability requiring external credentials that are unconfigured in this environment.
- **`NOT AVAILABLE`:** Metric that cannot be computed without external API execution (e.g., commercial API token costs).

### Master Evaluation Summary

| Evaluation Domain | Metric / Property | Result | Classification | Scope / Dataset Reference |
|---|---|:---:|:---:|---|
| **Test Suite Coverage** | Unit, Contract, Security, Integration | **236 passed, 0 failed** | **MEASURED** | Full test suite (`pytest -m "not integration"`) |
| **Safety Invariants** | Policy Boundary & Denial Gates | **12 / 12 PASS** | **MEASURED** | Security verification suite (`tests/security/`) |
| **MCP HTTP Latency** | `query_metrics` Round-Trip (p50) | **0.293 ms** | **MEASURED** | 50 iterations over HTTP transport (`evals/results/slice6/`) |
| **MCP HTTP Latency** | `query_metrics` Round-Trip (p95) | **0.442 ms** | **MEASURED** | 50 iterations over HTTP transport (`evals/results/slice6/`) |
| **MCP HTTP Latency** | `query_metrics` Round-Trip (p99) | **1.053 ms** | **MEASURED** | 50 iterations over HTTP transport (`evals/results/slice6/`) |
| **Trace Correlation** | Full Lifecycle Span Correlation | **100% (7/7 spans)** | **MEASURED** | Live scenario `INC-LIVE-PROD-20261005` |
| **Data Redaction** | Sensitive Credentials Scrubbing | **100% PASS** | **MEASURED** | Verified replacement with `[REDACTED_SECRET]` |
| **Data Redaction** | Internal Thought Scrubbing | **100% PASS** | **MEASURED** | Verified replacement with `[REDACTED_THOUGHT]` |
| **Fault Injection** | Fail-Closed Resilience | **PASS** | **MEASURED** | 5-layer fault injection test suite |
| **Remediation Benchmark** | Action Proposal & Policy Accuracy | **100% (20/20)** | **MEASURED** | 20 scenarios (5 allow, 5 require approval, 5 deny, 5 fail) |
| **Remediation Safety** | Unauthorized Action Execution Rate | **0.0%** | **MEASURED** | 95% Wilson CI: `[0.0%, 16.1%]` |
| **Retrieval Benchmark** | Dense Recall@5 | **0.7400** | **MEASURED** | 50 queries over Corpus v2.0.0 (Qdrant) |
| **Retrieval Benchmark** | Sparse BM25 Recall@5 | **0.7800** | **MEASURED** | 50 queries over Corpus v2.0.0 (BM25) |
| **Retrieval Benchmark** | Hybrid RRF Recall@5 | **0.7633** | **MEASURED** | 50 queries over Corpus v2.0.0 (Hybrid RRF) |
| **Retrieval Benchmark** | Hybrid + Rerank Recall@5 | **0.7900** | **MEASURED** | 50 queries over Corpus v2.0.0 (Hybrid + Rerank) |
| **Retrieval Benchmark** | Dense / Sparse Top-5 Overlap | **52.0%** | **MEASURED** | Demonstrates complementarity of hybrid retrieval |
| **Investigation Eval v1** | In-Distribution Root Cause Accuracy | **70.0%** | **MEASURED** | 30 held-out scenarios (Deterministic + Knowledge) |
| **Investigation Eval v2** | Adversarial Root Cause Accuracy | **0.0% (0/60)** | **MEASURED** | 60 adversarial scenarios; exposes deterministic ceiling |
| **Grounding Evaluation** | Citation Reference Validity | **100%** | **MEASURED** | 120 atomic claims; citations match canonical IDs |
| **Grounding Evaluation** | Semantic Entailment (NLI Judge) | *Not Evaluated* | **NOT AVAILABLE** | Requires external NLI judge model |
| **External LLM Execution** | Live Commercial API Invocation | *Unconfigured* | **NOT RUN** | Requires `SENTINELOPS_LLM_API_KEY` |
| **AWS Bedrock Gateway** | Live Cloud Managed Gateway | *Unconfigured* | **NOT RUN** | Requires AWS credentials / IAM role |
| **AWS Bedrock Runtime** | Live Cloud Managed Runtime | *Unconfigured* | **NOT RUN** | Requires AWS credentials / IAM role |

---

## 18. Security Architecture & Threat Model

SentinelOps treats all AI models and external inputs as potentially compromised.

### Core Security Controls
1. **Perimeter Authentication:** The MCP HTTP endpoint enforces Bearer token authentication. External requests lacking valid authorization headers receive an immediate HTTP 401.
2. **Deterministic Authorization Gate:** All mutating actions must pass through the standalone `PolicyEngine`. The policy engine has no LLM dependencies and evaluates rules deterministically.
3. **Role-Based Access Control (RBAC):** Actions require an authenticated `ActorContext` possessing the requisite `ActorRole` (`INCIDENT_COMMANDER`, `SRE_ON_CALL`, `AUTOMATED_AGENT`).
4. **Anti-Tamper Cryptographic Fingerprints:** Approval tokens bind cryptographically to SHA-256 hashes of action parameters. Modifying a parameter invalidates the token.

### Comprehensive Threat Model

| Threat ID | Threat Vector | Potential Impact | Implemented Mitigation | Residual Risk |
|---|---|---|---|---|
| **TM-01** | **Malicious Prompt Injection in Telemetry** | Attacker injects prompt escape sequences in log messages to hijack investigation. | Ingestion workers treat log messages as immutable string data. Prompts isolate telemetry inside strict data delimiters. | Advanced semantic confusion in unconstrained LLMs. |
| **TM-02** | **Compromised Knowledge Runbook** | Malicious actor modifies markdown runbook to instruct the model to execute destructive actions. | The `PolicyEngine` strictly forbids blacklisted actions (`DELETE_DATABASE`, `DROP_TABLE`) regardless of model recommendations. | Runbook could recommend non-optimal allowed actions. |
| **TM-03** | **Action Parameter Tampering** | Attacker intercepts approval request and changes target server to production database. | Approval tokens are cryptographically bound to the SHA-256 digest of original parameters. Any alteration invalidates approval. | None (mathematically prevented by cryptographic hashing). |
| **TM-04** | **Approval Replay Attack** | Attacker re-submits a previously authorized approval token to trigger unintended action. | Approval tokens contain single-use UUID nonces and transition to `CONSUMED` upon first execution. | None (replay requests fail state validation). |
| **TM-05** | **Privilege Escalation via Caller Headers** | Attacker injects forged `X-Actor-Role: INCIDENT_COMMANDER` HTTP headers. | Gateway adapters validate identity against perimeter cryptographic signatures (JWT / SigV4) before populating `ActorContext`. | Weak perimeter secrets if misconfigured. |
| **TM-06** | **Credential Leakage in Tracing** | API keys or database passwords leak into distributed trace collectors. | OpenTelemetry tracer recursively inspects and replaces secrets with `[REDACTED_SECRET]`. | Novel secret formats not matching redaction regexes. |
| **TM-07** | **Model Thought Exposure** | Sensitive internal chain-of-thought tokens or reasoning traces leak into public logs. | Internal scratchpads and reasoning tokens are scrubbed to `[REDACTED_THOUGHT]` before span export. | Unstructured reasoning emitted in plain text fields. |

---

## 19. Failure Modes & Recovery Procedures

SentinelOps is architected to fail closed, preserving system stability and state integrity when downstream components fail.

```text
Downstream Failure Detected
             │
             ├──► Insufficient Evidence ──────► Expand Query / Loop Back
             ├──► Unverified Diagnosis ───────► Re-Investigate (Bounded by max_iterations)
             ├──► Policy Denial ──────────────► Safe Halt (Transition to finalize_denied)
             ├──► Awaiting Approval ──────────► State Graph Interrupt & Checkpoint
             ├──► Action Execution Failure ───► Bounded Retry (Bounded by max_remediation_attempts)
             ├──► Post-Action Unrecovered ────► Escalate to On-Call Engineer (finalize_failed)
             └──► Database / Redis Down ──────► Retry with Exponential Backoff / Fail Closed
```

### Structured Failure Handlers

| Failure Condition | Detection Mechanism | Immediate System Response | Recovery / Escalation Path |
|---|---|---|---|
| **Insufficient Telemetry Evidence** | `verifier` node calculates low evidence coverage score | Graph loops back to `collect_evidence` to retrieve additional metrics | Bounded by `max_iterations=3`. If still unverified, transitions to `finalize` without proposing actions. |
| **Unverified Diagnosis** | Diagnostic confidence falls below threshold ($< 0.70$) | Graph rejects diagnosis proposal | Workflow loops back to evidence collection or safely terminates. |
| **Policy Engine Rejection** | `PolicyEngine` identifies blacklisted action or unauthorized role | Action execution is blocked; graph transitions to `finalize_denied` | Incident is logged with policy violation details; notifications dispatched to security team. |
| **Approval Timeout / Rejection** | Human operator denies approval or token expires ($> 3600\text{ s}$) | State graph resumes with rejection status | Workflow marks remediation as rejected and transitions to safe termination. |
| **Remediation Provider Failure** | `ActionProvider` returns error code (e.g., container crash) | `ActionResult` recorded as failed | Workflow attempts bounded retry (up to `max_remediation_attempts=2`). If exhausted, triggers `finalize_failed`. |
| **Persistent Degradation (Failed Verification)** | Post-action telemetry shows error rate remains above threshold | `verify_remediation` evaluates status as `NOT_RECOVERED` | Incident is **not** resolved. Graph triggers re-investigation or escalates to human on-call engineer. |
| **Redis / PostgreSQL Unavailability** | Async connection pool timeout | Ingestion worker and API return HTTP 503 / exponential backoff | Unacknowledged messages remain in Redis PEL. Processing resumes once storage recovers. |

---

## 20. Local Quick Start & Reproducibility Guide

Get SentinelOps running locally with full infrastructure in less than five minutes.

### Prerequisites
- **Python:** 3.11, 3.12, or 3.13
- **Docker & Docker Compose:** Installed and running locally
- **Git**

### Step 1: Clone & Environment Setup
```bash
git clone https://github.com/sentinelops/sentinelops.git
cd sentinelops

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies in editable mode with development packages
pip install --upgrade pip
pip install -e ".[dev]"
```

### Step 2: Launch Local Infrastructure
Start PostgreSQL 16, Redis 7, and Qdrant 1.13.0 via Docker Compose:
```bash
docker compose up -d postgres redis qdrant

# Verify infrastructure health
docker compose ps
```

### Step 3: Initialize Database & Knowledge Base
```bash
# Ingest operational runbooks and postmortems into Qdrant
sentinelops-ingest-knowledge
```

### Step 4: Run Application Services Locally
In separate terminal windows (or via background processes):
```bash
# 1. Start Telemetry Ingestion Worker
sentinelops-worker

# 2. Start Deterministic Detection Engine
sentinelops-detector

# 3. Start SentinelOps Orchestrator (LangGraph Runner)
sentinelops-orchestrator

# 4. Start FastAPI Management & MCP HTTP Server
sentinelops-api
```

### Step 5: Execute Automated Test Suite
Run the 236 offline unit, contract, security, and integration tests:
```bash
# Run all offline tests (excluding daemon-dependent integration tests)
PYTHONPATH=src pytest tests/ -m "not integration"

# Run contract generalization proofs
PYTHONPATH=src pytest tests/contract/

# Run security and policy invariant tests
PYTHONPATH=src pytest tests/security/
```

### Step 6: Reproduce Evaluations & Benchmarks
```bash
# Run Retrieval Benchmark (Dense, Sparse, Hybrid, Reranking over 50 queries)
python3 -m sentinelops.evals.run_retrieval_eval

# Run Controlled Remediation Benchmark (20 scenarios)
python3 -m sentinelops.evals.run_remediation_eval

# Run Slice 6 Production Validation & MCP HTTP Transport Latency Benchmark
python3 -m sentinelops.evals.run_slice6_eval
```

---

## 21. Repository Topology & Codebase Map

```text
sentinelops/
├── config/                                 # Declarative configuration files
│   └── detection_rules.yaml                # Declarative threshold detection rules
├── docs/                                   # Architectural documentation
│   └── reports/                            # Comprehensive engineering and audit reports (01 to 38)
├── evals/                                  # Machine-readable evaluation manifests and datasets
│   ├── datasets/                           # Versioned test scenarios and queries
│   └── results/                            # Benchmark output artifacts
│       ├── grounding/                      # Claim-level grounding evaluations
│       ├── investigation_v2/               # Adversarial Benchmark v2 results
│       ├── remediation/                    # Controlled remediation benchmark results
│       ├── retrieval/                      # Retrieval accuracy and latency results
│       └── slice6/                         # Production validation & transport latency results
├── knowledge/                              # Operational documents (runbooks, postmortems, architecture RFCs)
├── src/                                    # SentinelOps core source directory
│   └── sentinelops/
│       ├── agent/                          # LangGraph investigation & remediation engine
│       │   ├── nodes/                      # StateGraph nodes (intake, planner, collector, etc.)
│       │   ├── graph.py                    # StateGraph construction and compilation
│       │   └── state.py                    # InvestigationState TypedDict definition
│       ├── api/                            # FastAPI REST API endpoints
│       │   └── main.py                     # API server and route handlers
│       ├── approval/                       # Human-in-the-Loop approval service
│       │   └── service.py                  # ApprovalRequest handling and cryptographic token binding
│       ├── audit/                          # Immutable audit trail service
│       │   └── service.py                  # AuditEvent logging and persistence
│       ├── capabilities/                   # Pluggable internal capabilities
│       │   ├── evidence/                   # Telemetry evidence correlation
│       │   ├── knowledge/                  # BM25, embeddings, and reranker algorithms
│       │   └── llm/                        # Deterministic and real LLM providers
│       ├── config/                         # Centralized application settings
│       │   └── settings.py                 # Pydantic-settings configuration container
│       ├── detection/                      # Deterministic rule evaluation engine
│       │   ├── engine.py                   # Time-window metric evaluation
│       │   └── rules.py                    # Detection rule models
│       ├── domain/                         # Canonical domain model & abstract contracts
│       │   ├── contracts/                  # Python Protocol interfaces (zero vendor logic)
│       │   └── models/                     # Strongly typed Pydantic v2 domain models
│       ├── evals/                          # Benchmark execution runners
│       ├── ingestion/                      # Telemetry ingestion workers
│       │   └── worker.py                   # Redis Stream consumer worker
│       ├── integrations/                   # Concrete external provider adapters
│       │   ├── actions/                    # Mock and infrastructure action providers
│       │   ├── aws/                        # AWS Bedrock AgentCore Gateway & Runtime adapters
│       │   ├── event_bus/                  # Redis Streams EventBus implementation
│       │   ├── knowledge/                  # Qdrant and In-Memory knowledge providers
│       │   └── telemetry/                  # OpenTelemetry and Custom JSON adapters
│       ├── mcp/                            # Model Context Protocol implementation (2026-07-28)
│       │   ├── http_transport.py           # Real HTTP transport with Bearer auth
│       │   ├── protocol.py                 # JSON-RPC 2.0 and MCP schema definitions
│       │   ├── server.py                   # Base MCPServer container
│       │   └── servers/                    # 4 concrete MCP servers (telemetry, knowledge, change, remediation)
│       ├── observability/                  # Distributed tracing and metric collectors
│       │   ├── metrics.py                  # Lifecycle timer metrics
│       │   └── tracer.py                   # W3C tracer with automated recursive redaction
│       ├── orchestrator/                   # Event-driven workflow orchestrator
│       │   └── runner.py                   # Redis Stream incident consumer
│       ├── policy/                         # Deterministic PolicyEngine
│       │   ├── defaults.py                 # Default RBAC and action risk policies
│       │   └── engine.py                   # Policy evaluation logic
│       ├── simulator/                      # Synthetic telemetry generator for testing
│       └── storage/                        # Operational database access
│           └── postgres_store.py           # PostgreSQL asyncpg operational store
├── tests/                                  # Automated verification suite (236 tests)
│   ├── contract/                           # Generalization proofs & AST checks
│   ├── integration/                        # End-to-end pipeline & external adapter tests
│   ├── mcp/                                # MCP server and protocol compliance tests
│   ├── observability/                      # Distributed tracing and redaction tests
│   ├── security/                           # Policy boundary and prompt injection tests
│   └── unit/                               # Isolated subsystem unit tests
├── docker-compose.yml                      # Infrastructure orchestration (Postgres, Redis, Qdrant)
├── Dockerfile                              # Multi-stage production container build
└── pyproject.toml                          # Project dependencies, packaging, and tool configurations
```

---

## 22. Configuration Reference

All settings are configured via environment variables prefixed with `SENTINELOPS_` or defined in a local `.env` file (managed by `pydantic-settings`).

| Environment Variable | Default Value | Description | Sensitivity |
|---|---|---|:---:|
| `SENTINELOPS_SERVICE_NAME` | `sentinelops` | Logical service name for structured logs and tracing | Non-sensitive |
| `SENTINELOPS_ENVIRONMENT` | `development` | Deployment environment tag (`development`, `staging`, `production`) | Non-sensitive |
| `SENTINELOPS_LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | Non-sensitive |
| `SENTINELOPS_REDIS_URL` | `redis://localhost:6379/0` | Connection DSN for Redis Stream event bus | Non-sensitive |
| `SENTINELOPS_REDIS_TELEMETRY_STREAM` | `sentinel:telemetry` | Redis stream key for inbound raw telemetry | Non-sensitive |
| `SENTINELOPS_REDIS_INCIDENTS_STREAM` | `sentinel:incidents` | Redis stream key for emitted incidents | Non-sensitive |
| `SENTINELOPS_REDIS_CONSUMER_GROUP` | `sentinelops-workers` | Consumer group name for telemetry ingestion workers | Non-sensitive |
| `SENTINELOPS_POSTGRES_DSN` | `postgresql+asyncpg://sentinelops:sentinelops@localhost:5432/sentinelops` | Async connection string for PostgreSQL operational store | **Sensitive** |
| `SENTINELOPS_POSTGRES_POOL_SIZE` | `5` | SQLAlchemy async connection pool limit | Non-sensitive |
| `SENTINELOPS_DETECTION_RULES_PATH` | `config/detection_rules.yaml` | Path to declarative YAML detection rule definitions | Non-sensitive |
| `SENTINELOPS_DETECTION_INTERVAL_SECONDS` | `10.0` | Interval in seconds between detection evaluation cycles | Non-sensitive |
| `SENTINELOPS_QDRANT_URL` | `http://localhost:6333` | Network URL for Qdrant vector database | Non-sensitive |
| `SENTINELOPS_QDRANT_API_KEY` | `None` | Optional authentication key for managed Qdrant Cloud | **Sensitive** |
| `SENTINELOPS_QDRANT_COLLECTION` | `sentinelops_knowledge` | Collection name for operational knowledge indexing | Non-sensitive |
| `SENTINELOPS_RETRIEVAL_MODE` | `hybrid` | Active retrieval mode (`dense_only`, `sparse_only`, `hybrid`, `hybrid_plus_rerank`) | Non-sensitive |
| `SENTINELOPS_LLM_PROVIDER` | `deterministic` | Active LLM provider (`deterministic` or `real`) | Non-sensitive |
| `SENTINELOPS_LLM_MODEL` | `gpt-4o-mini` | Model identifier when `real` provider is selected | Non-sensitive |
| `SENTINELOPS_LLM_API_KEY` | `None` | API key for commercial LLM endpoint | **Sensitive** |
| `SENTINELOPS_LLM_BASE_URL` | `None` | Optional base URL for OpenAI-compatible LLM endpoints | Non-sensitive |
| `SENTINELOPS_API_HOST` | `0.0.0.0` | Network interface binding for FastAPI and MCP HTTP | Non-sensitive |
| `SENTINELOPS_API_PORT` | `8000` | Port number for FastAPI REST API and MCP HTTP server | Non-sensitive |

---

## 23. Open-Source Extension Guide

SentinelOps is architected for straightforward community extension. To integrate a new telemetry provider or infrastructure action runner, follow this pattern:

```text
New External System (e.g., Datadog / Kubernetes)
                       │
                       ▼
    Implement Canonical Protocol Adapter
    (Map vendor formats <-> Canonical Models)
                       │
                       ▼
          Add Contract Tests in tests/contract/
          (Verify zero core branching & semantic equivalence)
                       │
                       ▼
       Register in Configuration / Factory
```

### Adding a New Telemetry Adapter
1. **Implement the Protocol:** Create a new module under `src/sentinelops/integrations/telemetry/<provider_name>/adapter.py` implementing the `TelemetryAdapter` protocol:
   ```python
   from sentinelops.domain.contracts.protocols import TelemetryAdapter
   from sentinelops.domain.models.telemetry import TelemetryRecord

   class DatadogTelemetryAdapter:
       def normalize(self, raw_payload: dict[str, Any]) -> TelemetryRecord:
           # Map Datadog JSON schema into canonical TelemetryRecord
           ...
   ```
2. **Add Generalization Contract Tests:** Add test cases in `tests/contract/` proving that records emitted by your adapter evaluate identically in the `DetectionEngine` alongside existing adapters.
3. **Verify AST Invariance:** Run `pytest tests/contract/` to ensure no vendor-specific branching was added to `sentinelops.agent`.

---

## 24. Current Limitations & Technical Boundaries

To maintain technical credibility, SentinelOps explicitly documents its current engineering limitations:

1. **Unconfigured External Cloud APIs (`NOT RUN`):** In this offline local environment, live external commercial LLM APIs and live AWS Bedrock AgentCore managed cloud instances are unconfigured. While all local transports, adapters, and mock layers are empirically verified, live cloud latency and reliability metrics remain `NOT RUN`.
2. **Adversarial Reasoning Ceiling (Benchmark v2):** The offline deterministic rule engine achieved 0/60 root-cause accuracy on Benchmark v2. Benchmark v2 introduces adversarial scenarios (stale documentation, conflicting runbooks, lexical distractors) that require advanced semantic reasoning models to resolve.
3. **Absence of Semantic NLI Judge:** While citation validity is measured at 100% (verifying that citations reference real, canonical evidence objects), semantic truth entailment has not been evaluated by an automated Natural Language Inference (NLI) model.
4. **Local Evaluation Scale:** Benchmarks are run on held-out test datasets (50 retrieval queries, 60 investigation incidents, 20 remediation scenarios). These provide statistically significant local validation, but do not simulate internet-scale multi-tenant traffic.
5. **No Universal Security Claims:** Although the deterministic policy boundary successfully blocked 100% of tested prompt injection and privilege escalation attacks across 12 verified invariants, no system can guarantee universal immunity against novel, unobserved adversarial exploits.

---

## 25. Future Roadmap

The following architectural initiatives are tracked for future milestones:

- [ ] **Live External LLM Evaluation:** Execute Benchmark v2 against live commercial foundation models (Claude 3.5 Sonnet, GPT-4o) using `RealLLMProvider` with automated token and cost tracking.
- [ ] **Managed AWS Cloud Validation:** Execute the test harness against live AWS Bedrock AgentCore Gateway and Runtime deployments in an authenticated AWS account.
- [ ] **Automated Semantic NLI Grounding:** Integrate an automated Natural Language Inference model to score factual entailment between diagnosis claims and cited evidence.
- [ ] **Native Kubernetes ActionProvider:** Implement a production-grade `ActionProvider` executing rollbacks, pod restarts, and scaling directly via the official Kubernetes Python Client.
- [ ] **Kafka EventBus Implementation:** Provide an Apache Kafka / AWS MSK implementation of the `EventBus` protocol for high-throughput enterprise deployments.

---

## 26. Technical Glossary

- **ActionRequest:** A canonical domain object emitted by the investigation agent proposing a specific remediation action, target resource, and parameters.
- **ActorContext:** Authenticated context representing the entity executing or authorizing an action, including `actor_id` and `ActorRole`.
- **EpisodeKey:** A deterministic composite string (`{rule_id}::{service_name}::{namespace}`) used to deduplicate incidents in the operational store.
- **EvidenceItem:** A canonical, immutable piece of metric, log, trace, or knowledge evidence linked to an incident.
- **Exact-Action Binding:** Cryptographic parameter hashing ensuring an approval token cannot be used if parameters are modified.
- **LangGraph:** A cyclic graph workflow framework from LangChain used by SentinelOps to manage stateful, bounded agent investigations.
- **Model Context Protocol (MCP):** An open standard (revision 2026-07-28) enabling AI agents to discover tools and query operational resources via JSON-RPC 2.0.
- **OperationalStore:** The PostgreSQL persistence layer storing canonical telemetry records, incidents, and audit trails.
- **PolicyEngine:** The deterministic authorization engine that intercepts `ActionRequest` objects and outputs `ALLOW`, `REQUIRES_APPROVAL`, or `DENY`.
- **Reciprocal Rank Fusion (RRF):** An algorithmic method for combining ranked search results from dense vector search and sparse BM25 scoring into a single unified ranking.
- **RemediationStatus:** The measured operational recovery state after action execution (`RECOVERED`, `NOT_RECOVERED`, `DEGRADED`).
- **W3C Traceparent:** The standardized header format (`version-trace_id-parent_id-trace_flags`) used to propagate distributed trace context across service boundaries.

---

## 27. Technical Reports Index

The SentinelOps development history, architectural decisions, and formal verification milestones are documented in 38 engineering reports in `docs/reports/`:

| Report File | Title / Milestone | Key Focus |
|---|---|---|
| [`01_PRODUCT_REQUIREMENTS.md`](docs/reports/01_PRODUCT_REQUIREMENTS.md) | Product Requirements | Functional and non-functional requirements |
| [`02_GENERALIZATION_ARCHITECTURE.md`](docs/reports/02_GENERALIZATION_ARCHITECTURE.md) | Generalization Architecture | Provider-neutral core abstractions |
| [`03_SYSTEM_ARCHITECTURE.md`](docs/reports/03_SYSTEM_ARCHITECTURE.md) | Master System Architecture | End-to-end component specifications |
| [`04_DOMAIN_MODEL.md`](docs/reports/04_DOMAIN_MODEL.md) | Canonical Domain Model | Pydantic entity specifications |
| [`05_EVENT_CONTRACTS.md`](docs/reports/05_EVENT_CONTRACTS.md) | Event Contracts | Redis Streams message schemas |
| [`06_CONNECTOR_SPEC.md`](docs/reports/06_CONNECTOR_SPEC.md) | Connector Specifications | Telemetry adapter integration contracts |
| [`07_DETECTION_ENGINE.md`](docs/reports/07_DETECTION_ENGINE.md) | Detection Engine | Declarative threshold and rule evaluation |
| [`08_AGENT_DESIGN.md`](docs/reports/08_AGENT_DESIGN.md) | Agent Design & Workflow | LangGraph StateGraph topology |
| [`09_RETRIEVAL_ARCHITECTURE.md`](docs/reports/09_RETRIEVAL_ARCHITECTURE.md) | Knowledge & Retrieval | Qdrant hybrid vector & BM25 retrieval |
| [`10_POLICY_AND_SECURITY.md`](docs/reports/10_POLICY_AND_SECURITY.md) | Policy & Security Boundary | Deterministic remediation governance |
| [`11_EVALUATION_PLAN.md`](docs/reports/11_EVALUATION_PLAN.md) | Evaluation Plan | Benchmark metrics, datasets, and methodology |
| [`12_POC_RESULTS.md`](docs/reports/12_POC_RESULTS.md) | POC Results | Slice 1 implementation evidence |
| [`13_ARCHITECTURE_DECISIONS.md`](docs/reports/13_ARCHITECTURE_DECISIONS.md) | Architecture Decision Log | ADR-001 through ADR-030 |
| [`14_RUNBOOK.md`](docs/reports/14_RUNBOOK.md) | Operations Runbook | Deployment and troubleshooting procedures |
| [`15_DEMO_SCRIPT.md`](docs/reports/15_DEMO_SCRIPT.md) | End-to-End Demo Script | Step-by-step reproduction walkthrough |
| [`16_GENERALIZATION_PROOF.md`](docs/reports/16_GENERALIZATION_PROOF.md) | Generalization Proof | Static AST and contract verification |
| [`17_SLICE_2_RESULTS.md`](docs/reports/17_SLICE_2_RESULTS.md) | Slice 2 Verification | LangGraph AI investigation milestone |
| [`18_SLICE_3_EVALUATION_HARDENING.md`](docs/reports/18_SLICE_3_EVALUATION_HARDENING.md) | Slice 3 Evaluation Hardening | Retrieval bug fixes and Benchmark v2 |
| [`19_EVALUATION_AUDIT.md`](docs/reports/19_EVALUATION_AUDIT.md) | Evaluation Audit | Independent verification of metrics |
| [`20_SLICE_4_CONTROLLED_REMEDIATION.md`](docs/reports/20_SLICE_4_CONTROLLED_REMEDIATION.md) | Slice 4 Remediation Engine | Deterministic policy engine and safety gates |
| [`21_SLICE_4_VERIFICATION_AUDIT.md`](docs/reports/21_SLICE_4_VERIFICATION_AUDIT.md) | Slice 4 Verification Audit | Formal audit of remediation safety |
| [`22_SLICE_5_MCP_INTEROPERABILITY.md`](docs/reports/22_SLICE_5_MCP_INTEROPERABILITY.md) | Slice 5 MCP Interoperability | Model Context Protocol servers |
| [`23_SLICE_5_OBSERVABILITY.md`](docs/reports/23_SLICE_5_OBSERVABILITY.md) | Slice 5 Observability | W3C tracing and secret redaction |
| [`24_SLICE_5_AGENTCORE.md`](docs/reports/24_SLICE_5_AGENTCORE.md) | Slice 5 AgentCore Adapters | AWS Bedrock isolation adapters |
| [`25_SLICE_5_REAL_MODEL_EVALUATION.md`](docs/reports/25_SLICE_5_REAL_MODEL_EVALUATION.md) | Slice 5 Model Evaluation | External LLM harness specifications |
| [`26_SLICE_5_FINAL_VERIFICATION_AUDIT.md`](docs/reports/26_SLICE_5_FINAL_VERIFICATION_AUDIT.md) | Slice 5 Final Audit | Formal verification of Slice 5 |
| [`27_SLICE_5_FREEZE_RECORD.md`](docs/reports/27_SLICE_5_FREEZE_RECORD.md) | Slice 5 Freeze Record | Formal freeze milestone record |
| [`28_SLICE_6_PRODUCTION_VALIDATION.md`](docs/reports/28_SLICE_6_PRODUCTION_VALIDATION.md) | Slice 6 Production Validation | Real-world validation plan |
| [`29_SLICE_6_REAL_MODEL_EVALUATION.md`](docs/reports/29_SLICE_6_REAL_MODEL_EVALUATION.md) | Slice 6 Model Evaluation | Real LLM evaluation reporting |
| [`30_SLICE_6_MCP_HTTP_EVALUATION.md`](docs/reports/30_SLICE_6_MCP_HTTP_EVALUATION.md) | Slice 6 MCP HTTP Benchmark | Real HTTP transport latency measurements |
| [`31_SLICE_6_AGENTCORE_LIVE_EVALUATION.md`](docs/reports/31_SLICE_6_AGENTCORE_LIVE_EVALUATION.md) | Slice 6 AgentCore Live Audit | AWS live status classification |
| [`32_SLICE_6_FAULT_INJECTION.md`](docs/reports/32_SLICE_6_FAULT_INJECTION.md) | Slice 6 Fault Injection | Fail-closed resilience verification |
| [`33_SLICE_6_SECURITY_EVALUATION.md`](docs/reports/33_SLICE_6_SECURITY_EVALUATION.md) | Slice 6 Security Audit | Transport and policy boundary security |
| [`34_SLICE_6_FINAL_RESULTS.md`](docs/reports/34_SLICE_6_FINAL_RESULTS.md) | Slice 6 Final Results | Initial Slice 6 summary |
| [`35_SLICE_6_LIVE_EXTERNAL_VALIDATION.md`](docs/reports/35_SLICE_6_LIVE_EXTERNAL_VALIDATION.md) | Live External Validation | Environment preflight and live gap audit |
| [`36_SLICE_6_LIVE_LLM_EVALUATION.md`](docs/reports/36_SLICE_6_LIVE_LLM_EVALUATION.md) | Live LLM Evaluation Status | Formal `NOT RUN` classification report |
| [`37_SLICE_6_LIVE_AGENTCORE_EVALUATION.md`](docs/reports/37_SLICE_6_LIVE_AGENTCORE_EVALUATION.md) | Live AgentCore Status | Formal `NOT RUN` classification report |
| [`38_SLICE_6_FINAL_EMPIRICAL_VERDICT.md`](docs/reports/38_SLICE_6_FINAL_EMPIRICAL_VERDICT.md) | Final Empirical Verdict | Final Master Verdict: **PARTIAL PASS** |

---

## 28. License & Copyright

SentinelOps is open-source software released under the [MIT License](LICENSE).

Copyright (c) 2026 Rohith Gowda R. All rights reserved.

---

*SentinelOps is an open-source research and engineering initiative dedicated to safe, observable, and governed autonomous operations.*
