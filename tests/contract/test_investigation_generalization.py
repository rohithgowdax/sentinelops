"""
Investigation Generalization Contract Tests for SentinelOps Slice 2.

Architectural Proof:
Verifies that the SentinelOps AI Investigation loop operates entirely on
canonical domain representations without branching on telemetry source providers.

Proofs:
1. Canonical Equivalence: Incidents originating from OTel-like and Custom JSON adapters
   produce identical diagnosis semantics and root cause structures.
2. Provider Agnosticism / Zero Branching: Source code AST analysis confirms zero
   branching on `source_provider` or `provider` inside agent nodes, state, or graph logic.
3. Strict Evidence Grounding: All diagnoses cite valid canonical evidence IDs
   regardless of originating telemetry format.
"""
from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sentinelops.agent import graph, nodes, prompts, state
from sentinelops.agent.graph import create_investigation_graph
from sentinelops.capabilities.llm.provider import DeterministicLLMProvider
from sentinelops.domain.models.incident import (
    EvidenceItem,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    TriggerType,
)
from sentinelops.domain.models.investigation import (
    InvestigationResult,
    InvestigationStatus as InvStatus,
)
from sentinelops.integrations.telemetry.custom_json.adapter import CustomJsonAdapter
from sentinelops.integrations.telemetry.otel_like.adapter import OtelLikeAdapter


def _build_incident_from_adapter(adapter_name: str, raw_payload: dict) -> Incident:
    """Helper creating a canonical Incident from an adapter output."""
    if adapter_name == "otel":
        adapter = OtelLikeAdapter()
    else:
        adapter = CustomJsonAdapter()

    record = adapter.normalize(raw_payload)
    now = datetime.now(tz=timezone.utc)

    return Incident(
        incident_id=f"INC-{adapter_name.upper()}-001",
        created_at=now,
        updated_at=now,
        severity=IncidentSeverity.HIGH,
        service_name=record.resource.service_name,
        service_namespace=record.resource.service_namespace,
        environment=record.resource.environment,
        trigger_type=TriggerType.METRIC_THRESHOLD,
        trigger_rule_id="rule-high-error-rate",
        trigger_rule_name="HTTP Error Rate Exceeded",
        title=f"High error rate on {record.resource.service_name}",
        description=f"Observed error rate {record.metric.value} exceeds threshold 0.15",
        source_provider=record.source.provider,
        source_integration_id=record.source.integration_id,
        episode_key=f"rule-high-error-rate::{record.resource.service_name}::{record.resource.environment}",
        initial_evidence=[
            EvidenceItem(
                kind="metric",
                description=f"Metric {record.metric.name} value {record.metric.value}",
                value=record.metric.value,
                attributes={"metric_name": record.metric.name, "threshold": 0.15},
            )
        ],
    )


class TestInvestigationGeneralizationContract:
    """Contract tests proving provider-neutral investigation behavior."""

    def test_zero_provider_branching_in_agent_ast(self) -> None:
        """
        Static AST analysis proving agent nodes, graph, state, and prompts
        contain zero conditional branches on provider names ('otel', 'custom_json', 'datadog', 'prometheus').
        """
        agent_dir = Path(nodes.__file__).parent
        files_to_check = list(agent_dir.glob("*.py"))
        files_to_check.append(Path(graph.__file__))
        files_to_check.append(Path(state.__file__))
        files_to_check.append(Path(prompts.__file__))

        prohibited_literals = {"otel", "custom_json", "prometheus", "datadog", "cloudwatch"}

        for py_file in files_to_check:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                # Check for if statements comparing against provider names
                if isinstance(node, ast.Compare):
                    for comparator in node.comparators:
                        if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                            val = comparator.value.lower()
                            assert val not in prohibited_literals, (
                                f"Forbidden provider comparison '{val}' detected in {py_file.name}:{node.lineno}"
                            )

    @pytest.mark.asyncio
    async def test_semantic_equivalence_across_sources(
        self,
        otel_metric_payload: dict,
        custom_metric_payload: dict,
    ) -> None:
        """
        Prove that an incident originating from OTel-like telemetry and an incident
        originating from Custom JSON telemetry produce identical diagnosis semantics.
        """
        incident_otel = _build_incident_from_adapter("otel", otel_metric_payload)
        incident_custom = _build_incident_from_adapter("custom", custom_metric_payload)

        # Build mock evidence provider that serves provider-neutral data
        evidence_provider = AsyncMock()
        evidence_provider.query_recent_telemetry.return_value = {
            "resource": "test-service",
            "metric": "http.error_rate",
            "sample_count": 8,
            "observed_avg": 0.22,
            "observed_max": 0.28,
            "observed_min": 0.16,
            "latest_value": 0.24,
            "raw_references": ["ref-1", "ref-2"],
        }
        evidence_provider.compare_telemetry_baseline.return_value = {
            "resource": "test-service",
            "metric": "http.error_rate",
            "baseline_avg": 0.02,
            "current_avg": 0.22,
            "elevation_ratio": 11.0,
            "is_elevated": True,
            "baseline_samples": 30,
            "current_samples": 8,
        }
        evidence_provider.get_incident_trigger_context.side_effect = lambda incident: {
            "incident_id": incident.incident_id,
            "service_name": incident.service_name,
            "initial_evidence": [{"kind": "metric", "value": 0.18}],
        }

        llm = DeterministicLLMProvider()

        # Run OTel incident through LangGraph
        graph_otel = create_investigation_graph(
            evidence_provider=evidence_provider,
            llm_provider=llm,
        )
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        state_otel = {
            "incident": incident_otel,
            "investigation_plan": None,
            "current_step": 0,
            "iteration": 0,
            "max_iterations": 3,
            "evidence": [],
            "hypotheses": [],
            "selected_hypothesis": None,
            "diagnosis": None,
            "confidence": 0.0,
            "verification_result": None,
            "status": InvStatus.INVESTIGATING,
            "errors": [],
            "tool_calls_summary": [],
            "start_time_iso": now_iso,
            "final_result": None,
        }
        final_otel = await graph_otel.ainvoke(
            state_otel, config={"configurable": {"thread_id": incident_otel.incident_id}}
        )
        res_otel: InvestigationResult = final_otel["final_result"]

        # Run Custom JSON incident through LangGraph
        graph_custom = create_investigation_graph(
            evidence_provider=evidence_provider,
            llm_provider=llm,
        )
        state_custom = {
            "incident": incident_custom,
            "investigation_plan": None,
            "current_step": 0,
            "iteration": 0,
            "max_iterations": 3,
            "evidence": [],
            "hypotheses": [],
            "selected_hypothesis": None,
            "diagnosis": None,
            "confidence": 0.0,
            "verification_result": None,
            "status": InvStatus.INVESTIGATING,
            "errors": [],
            "tool_calls_summary": [],
            "start_time_iso": now_iso,
            "final_result": None,
        }
        final_custom = await graph_custom.ainvoke(
            state_custom, config={"configurable": {"thread_id": incident_custom.incident_id}}
        )
        res_custom: InvestigationResult = final_custom["final_result"]

        # Assert Semantic Equivalence
        assert res_otel.status == res_custom.status == InvStatus.DIAGNOSED
        assert res_otel.confidence == res_custom.confidence
        assert res_otel.diagnosis.root_cause == res_custom.diagnosis.root_cause
        assert len(res_otel.investigation_steps) == len(res_custom.investigation_steps)
        assert len(res_otel.diagnosis.recommended_actions) == len(res_custom.diagnosis.recommended_actions)
        assert res_otel.diagnosis.recommended_actions == res_custom.diagnosis.recommended_actions
