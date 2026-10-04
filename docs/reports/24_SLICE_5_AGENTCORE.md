# Slice 5: AWS Bedrock AgentCore Integration

**Status:** IMPLEMENTED (Adapters Verified, Live AWS Calls `NOT RUN`)  
**Date:** October 2026  
**Zero-Coupling Guarantee:** Core contains 0 imports of AWS SDKs/boto3  

---

## 1. Architectural Role: External Cloud Adapter

AWS Bedrock AgentCore is treated purely as an external deployment target and infrastructure adapter. SentinelOps Core retains complete vendor neutrality:

```text
External AWS Cloud / Bedrock AgentCore
                      │
           SigV4 / Bearer Token Auth
                      ▼
     ┌───────────────────────────────────┐
     │      AgentCoreGatewayAdapter      │
     │  - Target Aggregation Across MCP  │
     │  - Inbound Perimeter Auth Check   │
     │  - Outbound Identity/RBAC Mapping │
     └─────────────────┬─────────────────┘
                       │
                       ▼
     ┌───────────────────────────────────┐
     │      AgentCoreRuntimeAdapter      │
     │  - Host LangGraph Workflow Engine │
     │  - Context Extraction (Trace/User)│
     │  - State Checkpoint Persistence   │
     │  - Interrupt / Resume Dispatcher  │
     └─────────────────┬─────────────────┘
                       │
                       ▼
             SentinelOps Core Engine
```

---

## 2. Gateway Adapter (`AgentCoreGatewayAdapter`)

The gateway adapter aggregates tools across registered SentinelOps MCP servers into an AgentCore-compatible target schema:

* **Target Aggregation:** Dynamically queries `sentinelops-telemetry`, `sentinelops-knowledge`, `sentinelops-change`, and `sentinelops-remediation` via `server/discover` and surfaces a unified tool catalog.
* **Inbound Authorization:** Validates AWS SigV4 authorization headers or Bearer JWTs before allowing gateway access.
* **Identity Context Translation:** Maps incoming AWS IAM ARNs or STS session roles into canonical SentinelOps `ActorContext(actor_id, actor_role, tenant_id)`.

---

## 3. Runtime Adapter (`AgentCoreRuntimeAdapter`)

The runtime adapter hosts the SentinelOps LangGraph engine within an AWS Lambda or AgentCore container environment:

* **Workflow Invocation:** Translates incoming Bedrock invocation payloads into canonical `Incident` models and initial `InvestigationState`.
* **State Checkpointing:** Emits thread checkpoint snapshots so executions can be suspended when awaiting human approval.
* **Resume Handling:** Accepts Bedrock callbacks containing human approval tokens, resumes the LangGraph execution at the interrupted node, and returns the final `InvestigationResult`.

---

## 4. Live Environment Verification Status: `NOT RUN`

In adherence to truthfulness guidelines:
* **Unit and Contract Verification:** The gateway and runtime adapters pass all interface, schema, and perimeter authorization tests using mocked SigV4 tokens and mock LangGraph states.
* **Live AWS Execution:** Marked honestly as **`NOT RUN`**. No AWS credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`) are configured in the local development environment. SentinelOps does not fabricate mock calls as live AWS verification.
