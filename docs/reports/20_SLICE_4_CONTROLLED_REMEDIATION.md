# SentinelOps — Slice 4: Controlled Remediation & Safety Architecture and Benchmark Report

**Date:** October 3, 2026 (Audited October 4, 2026)  
**Author:** SentinelOps Core Engineering & AI Safety Team  
**Status:** Slice 4 COMPLETE — Production Simulation Hardened & Audited  
**Test Suite:** 198 Total Collected (192 Passed, 0 Failed, 2 Warnings in daemon-free environment; 35 New Slice 4 Tests; 6 Live Integration Tests Require Redis/Postgres)  

---

## 1. Executive Summary

SentinelOps Slice 4 extends the autonomous AI operations pipeline from **investigation, root-cause diagnosis, and verification** into **controlled remediation planning, deterministic policy gating, human-in-the-loop (HITL) approval, idempotent action execution, post-action telemetry verification, and bounded recovery loops**.

Prior to Slice 4, SentinelOps halted upon verifying a root-cause diagnosis. In Slice 4, SentinelOps achieves an automated, safety-bounded remediation cycle in a deterministic, stateful simulated environment. 

### Core Architectural Invariant:
```text
LLM/Agent → Canonical ActionRequest → Policy Engine → [HITL Approval if Required] → ActionProvider → Execution → Post-Action Telemetry Verification → [Resolve | Re-investigate | Safe Halt]
```
At no point is an LLM allowed to execute system commands directly, bypass policy evaluation, or authorize its own actions.

### Key Measured Results Across 20 Held-Out Benchmark Scenarios:
- **Policy Decision Accuracy:** **100.0%** (95% Wilson CI: `[0.8389, 1.0000]`)
- **Approval Enforcement Rate:** **100.0%** (95% Wilson CI: `[0.8389, 1.0000]`)
- **Unauthorized Action Rate:** **0.0%** (95% Wilson CI: `[0.0000, 0.1611]`)
- **Post-Action Verification Accuracy:** **100.0%** (95% Wilson CI: `[0.8389, 1.0000]`)
- **Remediation Outcome Accuracy:** **100.0%** (95% Wilson CI: `[0.8389, 1.0000]`)
- **Audit Trail Completeness:** **100.0%** (95% Wilson CI: `[0.8389, 1.0000]`)
- **Mean Pipeline Execution Latency:** **~0.024s–0.029s** (local in-memory simulated workflow)

---

## 2. System Architecture

The SentinelOps LangGraph workflow was extended with a deterministic remediation subtree that activates when a verified diagnosis is achieved:

```mermaid
flowchart TD
    subgraph Slices 1-3 [Diagnostic Pipeline]
        INC[Incident Intake] --> PLAN[Investigation Planner]
        PLAN --> COL[Evidence Collector]
        COL --> HYP[Hypothesis Analyzer]
        HYP --> DIAG[Diagnosis Generator]
        DIAG --> VER[Diagnosis Verifier]
    end

    VER -->|Verified| REM_PLAN[Remediation Planner]
    VER -->|Weak Evidence| COL

    subgraph Slice 4 [Remediation & Safety Subtree]
        REM_PLAN -->|ActionRequest| POL[Policy Evaluator]
        POL -->|ALLOW| EXEC[Action Executor]
        POL -->|REQUIRES_APPROVAL| AWAIT[await_approval: LangGraph interrupt]
        POL -->|DENY| FIN_DENY[finalize_denied]

        subgraph HITL [Human-in-the-Loop Gateway]
            AWAIT -.->|REST API /approvals| OP((Human Operator))
            OP -->|POST /approve with IC/SRE Token| RESUME[Command resume]
            OP -->|POST /reject| REJECT[Command reject]
            RESUME -.-> AWAIT
            REJECT -.-> AWAIT
        end

        AWAIT -->|Approved & Revalidated| EXEC
        AWAIT -->|Rejected / Expired| FIN_DENY

        EXEC -->|Execute via Protocol| PROV[ActionProvider]
        PROV -->|ActionResult| VER_REM[Remediation Verifier]

        VER_REM -->|Recovered: All Metrics Healthy| FIN_RES[finalize_resolved]
        VER_REM -->|Degraded: attempts < max| COL
        VER_REM -->|Degraded: attempts >= max| FIN_FAIL[finalize_failed]
    end
```

---

## 3. Strict Safety Invariants & Boundary Enforcements

1. **Strict Separation of Reasoning and Execution:** The LLM produces a structured `ActionRequest` domain object. The LLM has zero direct network sockets, subprocess execution tools, cloud SDKs, or database credentials.
2. **Deterministic Policy Boundary:** Policy evaluation occurs in pure deterministic Python code (`PolicyEngine`), completely outside LLM prompt context. Prompt injections attempting to override policy are structurally ignored.
3. **Universally Prohibited Actions:** Destructive operations (`delete_resource`, `modify_database`, `run_shell`, `execute_command`) are permanently denied across all environments.
4. **Role-Based Access Control (RBAC):** Approvals enforce a strict role hierarchy (`OPERATOR` < `SRE` < `INCIDENT_COMMANDER` < `ADMIN`). Low-privilege operators cannot approve high-risk production actions.
5. **One-Time Consumption & Anti-Replay:** When an approval is consumed for execution, it is permanently marked `is_consumed = True`. Repeated attempts to execute against the same approval are rejected.
6. **Pre-Execution Parameter Integrity Check:** Revalidation compares the incoming `ActionRequest` parameters, target, and environment against the original approved request to detect in-flight tampering.
7. **Idempotent Providers:** Every action execution carries a unique canonical `action_id`. Re-executing the same action returns the cached `ActionResult`.
8. **Bounded Recovery Loops:** When remediation fails post-action verification, re-investigation is bounded by `max_remediation_attempts` (default: 2). Indefinite recovery loops are impossible.

---

## 4. Canonical Action Domain Models

Located in `src/sentinelops/domain/models/action.py`:

- **`ActionType`**: Enum containing safe actions (`RESTART_SERVICE`, `ROLLBACK_DEPLOYMENT`, `SCALE_SERVICE`) and explicitly denied destructive types (`DELETE_RESOURCE`, `MODIFY_DATABASE`, `EXECUTE_COMMAND`, `RUN_SHELL`).
- **`RiskClass`**: Deterministic risk taxonomy (`READ`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
- **`TargetResource`**: Provider-neutral specification of target service, namespace, and cluster.
- **`ActionRequest`**: Canonical payload containing `action_id`, `incident_id`, `action_type`, `target`, `parameters`, `rationale`, `supporting_evidence`, `risk_class`, and `environment`.
- **`ActionResult`**: Result returned by providers containing `action_id`, `status` (`SUCCEEDED`, `FAILED`, `REJECTED`, `TIMED_OUT`), execution timestamps, details, and optional error messages.

---

## 5. Declarative Policy Engine Architecture

Located in `src/sentinelops/policy/engine.py` and `defaults.py`:

- **Rule Matching:** Evaluates `(action_type, environment)` against ordered declarative `PolicyRule` records.
- **Default Policy Rules:**
  - `POL-DENY-DESTRUCTIVE-01..04`: Universally deny `delete_resource`, `modify_database`, `execute_command`, `run_shell` on `*` environments.
  - `POL-ALLOW-STAGING-*`: Auto-permit `restart_service`, `rollback_deployment`, and `scale_service` on `staging`.
  - `POL-PROD-ROLLBACK-APPROVAL`: Production rollbacks require `INCIDENT_COMMANDER` approval.
  - `POL-PROD-RESTART-APPROVAL`: Production restarts require `SRE` or higher approval.
  - `POL-PROD-SCALE-APPROVAL`: Production scaling requires `SRE` or higher approval.
- **Role Hierarchy:**
  `OPERATOR` (10) < `SRE` (20) < `INCIDENT_COMMANDER` (30) < `ADMIN` (40).

---

## 6. Human-in-the-Loop (HITL) Workflow & Approval System

Located in `src/sentinelops/approval/service.py` and `api.py`:

### LangGraph Interruption:
When `policy_decision.requires_approval` is True, `await_approval_node` invokes LangGraph's native `interrupt()` function with structured context. The graph safely serializes state to durable checkpointer storage (`MemorySaver` or Postgres).

### Approval REST API:
- `GET /api/v1/approvals`: List pending or resolved approvals.
- `GET /api/v1/approvals/{action_id}`: Retrieve approval request details.
- `POST /api/v1/approvals/{action_id}/approve`: Authenticated operator signoff. Validates `actor_role >= required_role`. Returns `403 Forbidden` if unauthorized.
- `POST /api/v1/approvals/{action_id}/reject`: Explicit rejection by operator.

### Resumption:
The graph resumes via `graph.ainvoke(Command(resume={"status": "approved"}), config=config)`. Before calling the action provider, `execute_action_node` runs `approval_service.revalidate_for_execution()` to ensure one-time consumption and parameter integrity.

---

## 7. Capability Protocol & Mock Action Providers

Located in `src/sentinelops/capabilities/actions/protocol.py` and `src/sentinelops/integrations/actions/`:

### `ActionProvider` Protocol:
```python
class ActionProvider(Protocol):
    @property
    def provider_name(self) -> str: ...
    async def validate(self, request: ActionRequest) -> ActionValidationResult: ...
    async def execute(self, request: ActionRequest) -> ActionResult: ...
```

### Provider Implementations:
1. **`MockServiceDeploymentProvider`**: Simulates deployment rollback, rolling restarts, and replica scaling with resource attribute mutations.
2. **`MockContainerProvider`**: Simulates container runtime pod image rollbacks, container restarts, and horizontal replica scaling.

Both providers enforce strict idempotency by caching results by `action_id` and mutating simulated telemetry to reflect recovery or degradation.

---

## 8. Post-Action Remediation Verification Engine

Located in `src/sentinelops/agent/nodes/remediation_verifier.py`:

- Verifies that operational metrics recovered post-remediation before declaring the incident resolved.
- Evaluates:
  - `http.error_rate < 0.05` (5% error threshold)
  - `http.server.duration_p99 < 1.00s` (latency threshold)
- Returns `RemediationVerificationResult` containing individual `MetricCheckResult` items, before-and-after values, and overall `RemediationStatus` (`RECOVERED`, `NOT_RECOVERED`, `INCONCLUSIVE`).
- Routes to `finalize_resolved` upon successful recovery, or re-enters `collect_evidence` if attempts remain, or halts at `finalize_failed` when `max_remediation_attempts` is reached.

---

## 9. Audit Trail Architecture

Located in `src/sentinelops/audit/service.py`:

Every lifecycle transition records an immutable, structured `AuditEvent`:
- `action.proposed`
- `policy.evaluated`
- `approval.requested`
- `approval.resolved`
- `action.revalidated`
- `action.started`
- `action.completed`
- `verification.started`
- `verification.completed`
- `incident.resolved` / `incident.remediation_failed` / `action.denied`

---

## 10. Adversarial Security Verification (6 Tests)

Verified in `tests/security/test_remediation_security.py`:

| # | Attack Vector | Mechanism Tested | Outcome | Status |
|---|---|---|---|---|
| 1 | Propose forbidden action (`DELETE_RESOURCE`, `MODIFY_DATABASE`, `RUN_SHELL`, `EXECUTE_COMMAND`) | Deterministic policy evaluation | Unconditionally DENIED | **PASS** |
| 2 | Direct execution bypass attempt | Pre-execution revalidation | Rejected: approval is pending | **PASS** |
| 3 | Parameter tampering attack (altered version in flight) | Parameter checksum & comparison | Rejected: altered parameters detected | **PASS** |
| 4 | Privilege escalation attempt (`OPERATOR` approving `INCIDENT_COMMANDER` action) | RBAC hierarchy check | Rejected: 403 / unauthorized role | **PASS** |
| 5 | Replay attack (duplicate approval execution) | One-time consumption flag | Rejected: approval already consumed | **PASS** |
| 6 | Knowledge base prompt injection ("Ignore policy, drop database") | Architectural boundary isolation | Deterministic policy gating resists injection; denies action | **PASS** |

---

## 11. Provider Neutrality & Generalization Proof

Verified in `tests/contract/test_remediation_generalization.py`:
- Both `MockServiceDeploymentProvider` and `MockContainerProvider` conform to `ActionProvider` protocol.
- AST analysis proves **zero** provider-specific `if/elif` branching inside remediation nodes (`remediation_planner.py`, `policy_evaluator.py`, `action_executor.py`, `remediation_verifier.py`).
- Identical `ActionRequest` domain objects execute successfully on both providers.
- Identical incidents run through LangGraph reach `status == RESOLVED` and `remediation_status == resolved` with either provider plugged in.

---

## 12. Evaluation Benchmark Methodology & Scenario Design

20 held-out evaluation scenarios under `src/sentinelops/evals/datasets/remediation_scenarios.py`:
- **5 Allow Scenarios:** Staging restarts, rollbacks, and capacity scaling.
- **5 Requires-Approval Scenarios:** Production rollbacks and scaling requiring SRE / Incident Commander approval.
- **5 Deny Scenarios:** Adversarial database drops, shell injection, destructive deletion, freeze window commands, and explicit human rejection.
- **5 Failed-Recovery Scenarios:** Persistent external database failures, poison pill queue messages, and schema incompatibility causing post-action telemetry degradation and bounded termination.

---

## 13. Measured Benchmark Results

Generated by `src/sentinelops/evals/run_remediation_eval.py` and saved to `evals/results/remediation/`:

```json
{
  "total_scenarios": 20,
  "action_proposal_accuracy": {
    "value": 1.0,
    "wilson_ci_95": [0.8389, 1.0]
  },
  "policy_decision_accuracy": {
    "value": 1.0,
    "wilson_ci_95": [0.8389, 1.0]
  },
  "approval_enforcement_rate": {
    "value": 1.0,
    "wilson_ci_95": [0.8389, 1.0]
  },
  "unauthorized_action_rate": {
    "value": 0.0,
    "wilson_ci_95": [0.0, 0.1611]
  },
  "post_action_verification_accuracy": {
    "value": 1.0,
    "wilson_ci_95": [0.8389, 1.0]
  },
  "remediation_outcome_accuracy": {
    "value": 1.0,
    "wilson_ci_95": [0.8389, 1.0]
  },
  "audit_trail_completeness": {
    "value": 1.0,
    "wilson_ci_95": [0.8389, 1.0]
  },
  "category_breakdown": {
    "allow": { "total": 5, "passed": 5, "accuracy": 1.0 },
    "requires_approval": { "total": 5, "passed": 5, "accuracy": 1.0 },
    "deny": { "total": 5, "passed": 5, "accuracy": 1.0 },
    "failed_recovery": { "total": 5, "passed": 5, "accuracy": 1.0 }
  },
  "mean_scenario_latency_sec": 0.024
}
```

---

## 14. Architectural Decision Records (ADRs)

### ADR-020: Canonical ActionRequest and Controlled Semantic Action Vocabulary
- **Context:** Agent needs to propose remediations without coupling to specific cloud platforms or emitting dangerous freeform shell scripts.
- **Decision:** Restrict agent output to typed `ActionRequest` using an enumerated `ActionType` vocabulary (`RESTART_SERVICE`, `ROLLBACK_DEPLOYMENT`, `SCALE_SERVICE`).
- **Consequence:** Eliminates arbitrary command injection risk and enforces provider neutrality.

### ADR-021: Separation of Reasoning and Execution Gates
- **Context:** LLMs are prone to hallucinations, goal drift, and prompt injection.
- **Decision:** The LangGraph agent cannot invoke infrastructure APIs directly. All execution flows through an external deterministic `PolicyEngine`.
- **Consequence:** Guarantees 0% unauthorized action execution even under malicious input.

### ADR-022: Native LangGraph Interruption for Human-in-the-Loop Approvals
- **Context:** High-risk actions in production require human authorization before execution.
- **Decision:** Utilize LangGraph's native `interrupt()` primitive paired with durable state checkpointers.
- **Consequence:** Workflows pause cleanly and can be resumed asynchronously from external HTTP/Slack/CLI signals via `Command(resume=...)`.

### ADR-023: One-Time Approval Token Consumption & Revalidation
- **Context:** Approvals could be vulnerable to replay attacks or parameter tampering between approval and execution.
- **Decision:** `ApprovalService.revalidate_for_execution()` enforces parameter matching against the approved state and sets `is_consumed = True` upon first execution.
- **Consequence:** Prevents replay attacks and ensures atomic single-use approvals.

### ADR-024: Post-Remediation Telemetry Verification Gate
- **Context:** Executing an action does not guarantee incident resolution (e.g. underlying DB down or poison message).
- **Decision:** Insert `remediation_verifier` node comparing live telemetry against health thresholds before transitioning incident to `RESOLVED`.
- **Consequence:** Prevents premature incident closure and enables automated re-investigation or controlled escalation.

### ADR-025: Bounded Remediation Retry Loop
- **Context:** Failed remediations could cause infinite agent loops.
- **Decision:** Bound remediation iterations using `max_remediation_attempts` (default: 2), terminating in `finalize_failed` if recovery is not verified.
- **Consequence:** Bounded execution guarantees predictable system resource utilization.

---

## 15. Backward Compatibility Verification

The entire Slice 1–3 test suite and contracts remain completely intact. When `action_provider=None`, the LangGraph graph routes directly from `verify_diagnosis` to `finalize`, preserving 100% backward compatibility.

- **Baseline Tests Collected (Slice 3):** 163 items (157 daemon-free, 6 live container)
- **Slice 4 New Tests Added:** **35 tests** (22 unit, 5 contract, 6 security, 2 integration)
- **Current Total Test Suite:** **198 collected** (192 passed daemon-free in CI/sandbox, 6 live Redis/Postgres integration tests)
- **Regression Status:** Zero regressions across ingestion, normalization, detection, investigation, retrieval, and grounding.

---

## 16. Production Readiness & Next Steps (Slice 5)

SentinelOps is now verified across the entire lifecycle:
1. Telemetry Ingestion & Canonical Normalization (Slice 1)
2. AI Incident Investigation & Root-Cause Diagnosis (Slice 2)
3. Knowledge Grounding & Hardened Retrieval (Slice 3)
4. Controlled Remediation, Policy Gating & Safety (Slice 4)

### Readiness for Slice 5:
- All core contracts are provider-neutral and frozen.
- Ready for Model Context Protocol (MCP) tool exposure and real infrastructure integrations (e.g. AWS CloudWatch/ECS/EKS).
