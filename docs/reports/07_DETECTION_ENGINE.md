# SentinelOps — Detection Engine

## Purpose

The detection engine evaluates configured rules against canonical telemetry to determine when an incident condition is active. It is deterministic, configurable, provider-neutral, and fully testable in isolation (no I/O in the core evaluation function).

## Architecture

```
config/detection_rules.yaml
         │
    rules.py (load_rules)
         │
    List[DetectionRule]
         │
    loop.py (DetectionLoop)
         │
    ┌────┴────────────────────────────────────┐
    │  For each rule:                         │
    │   store.query_recent_metrics()          │
    │      ↓                                  │
    │   engine.evaluate_rule()  ← PURE FN    │
    │      ↓ EvaluationResult                 │
    │   if fired AND no active episode:       │
    │     create Incident                     │
    │     store.save_incident()               │
    │     bus.publish_incident()              │
    └─────────────────────────────────────────┘
```

---

## Rule Schema (YAML)

```yaml
rules:
  - rule_id: rule-001-elevated-service-errors   # stable unique ID (never reuse)
    name: Elevated Service Error Rate           # human-readable
    signal: metric                              # "metric" only in slice 1
    metric: http.error_rate                     # canonical metric name
    operator: gt                                # gt | gte | lt | lte | eq
    threshold: 0.10                             # boundary value in canonical units
    window_seconds: 60                          # look-back window
    severity: critical                          # low | medium | high | critical
    service_filter: payments-service            # scope to one service (required in slice 1)
    environment: null                           # optional environment scope
    aggregation: latest                         # latest | mean | max | min
    enabled: true                               # false = skip without removing
    description: >
      Fires when error_rate > 10% in the last 60 seconds.
```

### Field Specifications

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `rule_id` | `str` | Yes | — | Stable identifier; never reuse/rename |
| `name` | `str` | Yes | — | Human-readable name |
| `signal` | `"metric"` | Yes | — | Signal type (only `metric` in slice 1) |
| `metric` | `str` | Yes | — | Canonical metric name to evaluate |
| `operator` | `Operator` | Yes | — | Comparison operator |
| `threshold` | `float` | Yes | — | Boundary value in canonical units |
| `window_seconds` | `int` | Yes | — | Look-back window in seconds (> 0) |
| `severity` | `str` | Yes | — | Incident severity if fired |
| `service_filter` | `str\|null` | No | `null` | Scope to a specific service |
| `environment` | `str\|null` | No | `null` | Scope to a specific environment |
| `aggregation` | `Aggregation` | No | `latest` | How to reduce multiple samples |
| `enabled` | `bool` | No | `true` | If false, rule is skipped |
| `description` | `str` | No | `""` | Human-readable explanation |

---

## Operators

| Operator | Meaning | Example |
|---|---|---|
| `gt` | greater than | `observed > threshold` |
| `gte` | greater than or equal | `observed >= threshold` |
| `lt` | less than | `observed < threshold` |
| `lte` | less than or equal | `observed <= threshold` |
| `eq` | equal | `observed == threshold` |

All comparisons are on floating-point values. `eq` should be used with caution for non-integer values.

---

## Aggregations

The aggregation reduces multiple metric samples within the time window into a single comparable value.

| Aggregation | Behaviour |
|---|---|
| `latest` | Uses the most recent sample (records ordered by timestamp asc, takes `[-1]`) |
| `mean` | Arithmetic mean of all samples in the window |
| `max` | Maximum value across all samples |
| `min` | Minimum value across all samples |

> **Ordering invariant:** The OperationalStore always returns records ordered by `timestamp ASC`. Aggregations depend on this ordering.

---

## The Pure Evaluation Function

```python
def evaluate_rule(
    rule: DetectionRule,
    records: list[TelemetryRecord],
    service_name: str,
    environment: str | None,
) -> EvaluationResult:
```

**Properties:**
- No I/O (no database calls, no Redis calls)
- Deterministic for the same inputs
- Returns `fired=False` for empty record list (no spurious alerts)
- Filters records by `record.metric.name == rule.metric` (canonical field, not provider field)
- Returns `sample_count=0` and `observed_value=None` if no matching metric records

**EvaluationResult fields:**

| Field | Type | Description |
|---|---|---|
| `rule` | `DetectionRule` | The rule that was evaluated |
| `fired` | `bool` | Whether the condition was met |
| `observed_value` | `float\|None` | The aggregated value observed |
| `sample_count` | `int` | Number of metric samples used |
| `evaluated_at` | `datetime` | When evaluation occurred |
| `service_name` | `str` | Service being evaluated |
| `environment` | `str\|None` | Environment scope |
| `episode_key` | `str` | `rule_id::service_name::environment` |

---

## Deduplication via Episode Key

The episode key is constructed as:
```
{rule.rule_id}::{service_name}::{environment or "any"}
```

Before creating a new incident, the detection loop checks `store.get_active_episode(episode_key)`. If an OPEN or INVESTIGATING incident exists for this key, no new incident is created. This check is **persistent** (database-backed), so it survives process restarts.

The deduplication is proven by `tests/unit/test_detection_engine.py::TestEvaluateRule::test_episode_key_stable` and `tests/integration/test_pipeline.py::TestDetectionPipeline::test_deduplication_no_duplicate_incident`.

---

## Detection Loop Execution

The loop runs every `SENTINELOPS_DETECTION_INTERVAL_SECONDS` (default: 10 seconds).

**Per-cycle steps:**
1. For each enabled rule:
   a. Determine service list (from `service_filter` in slice 1)
   b. Compute `since = now - window_seconds`
   c. Call `store.query_recent_metrics(service, metric, since)` — canonical query
   d. Call `evaluate_rule(rule, records, service, environment)` — pure, no I/O
   e. If `fired`:
      - Check `store.get_active_episode(episode_key)`
      - If no active episode: create incident, persist, publish
2. Log the cycle; sleep for `interval_seconds`

Errors within a cycle are caught and logged; the loop continues.

---

## Actual Deployed Rules (config/detection_rules.yaml)

```yaml
rules:
  - rule_id: rule-001-elevated-service-errors
    metric: http.error_rate
    operator: gt
    threshold: 0.10        # 10% error rate
    window_seconds: 60
    severity: critical
    aggregation: latest

  - rule_id: rule-002-high-latency-p99
    metric: http.latency.p99
    operator: gt
    threshold: 300.0       # 300ms
    window_seconds: 60
    severity: high
    aggregation: latest

  - rule_id: rule-003-mean-error-rate-critical
    metric: http.error_rate
    operator: gt
    threshold: 0.15        # 15% sustained mean
    window_seconds: 120
    severity: critical
    aggregation: mean
```

---

## Extending the Engine

The enum-based design allows new operators and aggregations without changing the evaluation loop:

**New operator:**
```python
class Operator(str, Enum):
    GT = "gt"
    # ... existing ...
    BETWEEN = "between"   # add here
```
Then add a case to `_compare()` in `engine.py`.

**New aggregation:**
```python
class Aggregation(str, Enum):
    LATEST = "latest"
    # ... existing ...
    PERCENTILE_95 = "p95"   # add here
```
Then add a case to `_aggregate()` in `engine.py`.

No changes needed to `loop.py`, `rules.py` schema validation, or any other component.

---

## Limitations in Slice 1

- `service_filter` is required in every rule; the loop does not auto-discover services from the store
- No composite rules (rules that combine multiple metrics)
- No rate-of-change / derivative operators
- No anomaly detection or statistical models
- No LLM integration in detection (by design — deterministic only)
- Window is a simple time range; no sliding window aggregation with sub-windows
