# SentinelOps — Architecture Decision Log

## ADR-001 — Canonical domain model as the core abstraction

### Context
SentinelOps must accept telemetry from multiple external observability systems (OTel, custom agents, Datadog, etc.) and process all of them through a single detection pipeline. A naive implementation would branch on provider throughout the core.

### Decision
Define a canonical domain model (`TelemetryRecord`, `Incident`, etc.) in `sentinelops.domain.models`. All external formats are normalized into this model by adapters before entering any core component. The core pipeline depends only on canonical types.

### Alternatives
- **Multi-schema pipelines:** Separate detection pipelines per provider. Rejected because it duplicates rules, testing, and creates divergent behavior.
- **Union types / discriminated union:** A single model with provider-specific optional fields. Rejected because it leaks vendor semantics into the core.

### Consequences
- Adding a new telemetry source requires only a new adapter — no core changes.
- All detection rules operate on canonical field names.
- The core is testable without any real infrastructure.
- Adapters must map unit semantics (e.g., percent → ratio) — this is explicit and tested.

---

## ADR-002 — Redis Streams for EventBus with consumer groups

### Context
The EventBus must provide ordered, at-least-once delivery with explicit acknowledgement. The system must not silently drop failed messages.

### Decision
Use Redis Streams (`XADD`, `XREADGROUP`, `XACK`) with consumer groups. Two streams: `sentinel:telemetry` and `sentinel:incidents`. Failed messages remain in the PEL (pending-entries list) and are not automatically dropped.

### Alternatives
- **Kafka:** More durable, better for large-scale. Rejected for slice 1 because it adds operational complexity without benefit at this scale. Kafka remains the right choice for a production deployment.
- **In-process queue (asyncio.Queue):** Simpler but not persistent; doesn't survive process restarts. Rejected.
- **RabbitMQ:** Good fit but adds another infrastructure dependency without clear advantage over Redis Streams for this use case.

### Consequences
- Redis must be running for the system to function.
- Failed messages accumulate in PEL; a PEL recovery mechanism is needed in a future slice.
- Stream retention is unbounded in slice 1; production deployments must configure `MAXLEN`.
- The EventBus implementation is behind a Protocol, so switching to Kafka in a later slice requires only a new implementation of `EventBus`.

---

## ADR-003 — PostgreSQL for OperationalStore

### Context
Canonical telemetry and incidents must be persisted for detection queries (time-window lookups) and API reads. The store must support idempotent writes.

### Decision
Use PostgreSQL with SQLAlchemy async + asyncpg. Telemetry is written with `INSERT … ON CONFLICT DO NOTHING` on `event_id`. Incidents use the same pattern on `incident_id`.

### Alternatives
- **TimescaleDB:** Better for time-series metrics at scale. Rejected for slice 1 to avoid an additional database product. Can be migrated to by changing only the store implementation.
- **SQLite:** Simpler, no infrastructure needed. Rejected because the async support is limited and it would require replacement before production.
- **Redis as primary store:** Fast, but limited query capability. Rejected because time-window queries over large datasets become unwieldy.

### Consequences
- The OperationalStore is behind a Protocol; alternative implementations (TimescaleDB, ClickHouse) can be added in later slices.
- Time-window queries are indexed on `(service_name, metric_name, timestamp)`.
- Integration tests require a running PostgreSQL instance.

---

## ADR-004 — Deterministic rule-based detection in slice 1 (no LLM)

### Context
The specification requires that the detection layer be deterministic and testable, with the LLM/agent entering only after an incident exists.

### Decision
The detection engine evaluates YAML-configured threshold rules against canonical stored metrics. The pure `evaluate_rule()` function has no I/O. No LLM, ML model, or statistical anomaly detector is used in this slice.

### Alternatives
- **ML-based anomaly detection:** More sophisticated but non-deterministic in training and evaluation. Would make testing much harder. Reserved for a future slice.
- **LLM-based threshold judgement:** Explicitly prohibited by the architectural invariant "LLM → ActionRequest → Policy → Approval → ActionProvider" and the requirement that the detection layer be deterministic.

### Consequences
- All detection failures are understandable and reproducible.
- Rules must be explicitly configured; the system cannot discover thresholds automatically.
- False positive rate depends on rule quality.
- Future slices can add anomaly detection as an additional signal source without changing the core incident lifecycle.

---

## ADR-005 — Percent-to-ratio normalization in CustomJsonAdapter

### Context
The custom JSON format reports error rate as a percentage (0–100), while the OTel format uses a ratio (0–1). Detection rules use a single threshold value. Without normalization, rules would fire differently depending on which adapter produced the data — violating the generalization invariant.

### Decision
`CustomJsonAdapter.normalize()` divides `metric_value` by 100 and sets `unit = "ratio"` when `unit` is `"percent"` or `"%"` and `value > 1.0`. Detection rules use ratio thresholds (e.g., `0.10` for 10%).

### Alternatives
- **Dual thresholds per rule:** Have adapters declare their unit and let the engine apply different thresholds per unit. Rejected because it reintroduces provider awareness into the detection engine.
- **Rule-level unit configuration:** Rules specify expected unit. Rejected for the same reason.

### Consequences
- All rules use ratio units for percentage-type metrics.
- The normalization is explicit and tested (`test_normalizes_percent_to_ratio`).
- Adapter documentation must clearly state this normalization.
- Raw values are preserved in `raw_payload` so the original external format is not lost.

---

## ADR-006 — Episode key for incident deduplication

### Context
A detection rule firing continuously (e.g., error rate stays high for 10 minutes) must not create a new incident every 10 seconds. Deduplication must be persistent across process restarts.

### Decision
Each evaluation result has a stable `episode_key = "{rule_id}::{service_name}::{environment}"`. Before creating an incident, the detection loop checks `store.get_active_episode(episode_key)`. If an OPEN or INVESTIGATING incident exists, no new incident is created.

### Alternatives
- **In-memory set of active episodes:** Simple but not persistent. Rejected because a process restart would create duplicate incidents.
- **Redis-based episode tracking:** Faster lookup but adds Redis dependency to the detection loop for a non-streaming use case. Rejected in favor of database consistency.

### Consequences
- Deduplication is consistent across multiple detector instances (horizontal scaling).
- If an incident is resolved and the condition recurs, a new incident will be created — correct behavior.
- The `get_active_episode` query uses an indexed `(episode_key, status)` compound index.

---

## ADR-007 — pyproject.toml as the single build/dependency manifest

### Context
The repository uses a uv-based pyproject.toml at root for the existing Airflow project. SentinelOps needs its own dependency set.

### Decision
Create a separate `sentinelops/pyproject.toml` for the SentinelOps sub-project. This isolates dependencies, allows independent versioning, and prevents conflicts with the unrelated ML project at root.

### Consequences
- Installation: `pip install -e "sentinelops[dev]"` from the project root.
- Tests run from the `sentinelops/` directory with `PYTHONPATH=src`.
- The Dockerfile installs from `sentinelops/pyproject.toml`.

---

## ADR-008 — Explicit LangGraph StateGraph topology with bounded loop for AI investigation

### Context
Slice 2 requires an AI investigation loop that takes an incident, plans queries, collects evidence, formulates hypotheses, synthesizes diagnoses, and verifies evidence sufficiency. A naive ReAct/one-call LLM loop can loop infinitely or produce free-form ungrounded text.

### Decision
Implement an explicit LangGraph `StateGraph` with 7 discrete typed nodes:
`incident_intake -> build_investigation_plan -> collect_evidence -> analyze_evidence -> diagnose -> verify_diagnosis -> (insufficient & iter < 3 -> collect_evidence | sufficient/iter=3 -> finalize) -> END`.
Enforce a hard loop bound of `max_iterations = 3`. If verification cannot be confirmed in 3 cycles, terminate gracefully with `INSUFFICIENT_EVIDENCE`.

### Alternatives
- **Generic ReAct agent with tool calling:** Hard to test deterministically, vulnerable to infinite tool calling, and leaks raw prompts between tools. Rejected.
- **Single-prompt LLM call:** Incapable of multi-step retrieval, correlation, or iterative baseline comparisons. Rejected.

### Consequences
- Every stage of investigation is isolated, unit-testable, and auditable.
- State transitions are strictly typed via Pydantic models.
- Guarantees termination in at most 3 cycles.

---

## ADR-009 — Capability abstraction (TelemetryEvidenceProvider) isolating agent from storage

### Context
Agent nodes must query historical operational metrics, compute elevation ratios, and examine incident trigger context. If agent nodes write raw SQL or connect directly to Redis, the agent layer becomes tightly coupled to PostgreSQL/Redis schemas.

### Decision
Define a provider-agnostic capability protocol `TelemetryEvidenceProvider` with three methods: `query_recent_telemetry`, `compare_telemetry_baseline`, and `get_incident_trigger_context`. Concrete implementation `PostgresTelemetryEvidenceProvider` translates queries into `OperationalStore` calls. Agent nodes only interact with this protocol.

### Alternatives
- **Direct SQL queries inside agent nodes:** Severely violates modularity and prevents swapping storage engines (e.g. TimescaleDB, ClickHouse). Rejected.
- **MCP server:** Deferred to future slices to avoid unnecessary network hops and infrastructure overhead during Slice 2.

### Consequences
- Agent nodes remain 100% database-agnostic.
- Testing agent nodes with mocks requires zero database infrastructure.
- Zero raw SQL or database connection objects leak into graph state.

---

## ADR-010 — Pluggable LLMProvider with DeterministicLLMProvider for CI & testing

### Context
CI and automated test suites must run deterministically, fast, and without reliance on third-party API keys, billing, or external internet access.

### Decision
Create a generic `LLMProvider` protocol covering `generate_plan`, `analyze_hypotheses`, `generate_diagnosis`, and `verify_diagnosis`. Implement `DeterministicLLMProvider` which correlates real quantitative observations (mean values, peak spikes, elevation ratios) to generate verified diagnoses citing valid evidence IDs. Swappable for Claude/Gemini/OpenAI in production.

### Consequences
- 100% of graph flow, node logic, and contract tests run completely offline and deterministically in milliseconds.
- Strict evidence citation invariant is rigorously verified in automated tests.

---

## ADR-011 — Durable State Checkpointing with incident_id Thread ID

### Context
Incident investigations must be auditable, inspectable, and resilient to transient process failures.

### Decision
Use LangGraph's checkpointer mechanism (`MemorySaver` for testing/POC, pluggable to PostgreSQL/Redis) configured with `configurable = {"thread_id": incident.incident_id}`.

### Consequences
- Investigation state at every step can be inspected or resumed by passing the canonical incident ID.
- Clean separation between thread sessions.

