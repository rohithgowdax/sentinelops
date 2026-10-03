"""
LLM Provider Abstraction and Implementations for SentinelOps Investigation.

Provides pluggable language model reasoning implementations satisfying `LLMProvider` protocol:
- `DeterministicLLMProvider`: Evidence-grounded, deterministic provider for fast, reproducible, offline tests.
- Formulates plans, hypotheses, diagnoses, and verification results solely from collected evidence.

Architectural Rule:
The system diagnoses from EVIDENCE, not from predefined answers.
No expected diagnosis or ground truth is hardcoded in prompts or provider logic.
"""
from __future__ import annotations

import statistics
from typing import Any

import structlog

from sentinelops.domain.contracts.protocols import LLMProvider
from sentinelops.domain.models.incident import Incident
from sentinelops.domain.models.investigation import (
    Diagnosis,
    Hypothesis,
    InvestigationEvidence,
    InvestigationPlan,
    InvestigationStep,
    VerificationResult,
)
from sentinelops.domain.models.knowledge import KnowledgeQuery


log = structlog.get_logger(__name__)


class DeterministicLLMProvider:
    """
    Deterministic, evidence-grounded implementation of LLMProvider.

    Analyzes structured observations directly from collected evidence to formulate
    hypotheses and diagnoses with complete audit traceability.
    """

    def __init__(self, confidence_threshold: float = 0.70) -> None:
        """
        Initialize provider.

        Args:
            confidence_threshold: Minimum confidence required for verification (default: 0.70).
        """
        self._confidence_threshold = confidence_threshold

    async def generate_plan(
        self,
        incident: Incident,
        available_capabilities: list[str],
    ) -> InvestigationPlan:
        """
        Formulate an investigation plan based on incident trigger context.
        """
        steps: list[InvestigationStep] = [
            InvestigationStep(
                id="trigger_context",
                description="Extract trigger context, rule definition, and initial evidence",
                capability="trigger_context",
                params={"incident_id": incident.incident_id},
            ),
        ]

        # Extract metric name from rule or initial evidence
        metric_name = "http.error_rate"
        if incident.initial_evidence:
            for item in incident.initial_evidence:
                if "http.latency" in item.description or "latency" in item.description:
                    metric_name = "http.latency.p99"
                elif "http.error" in item.description or "error" in item.description:
                    metric_name = "http.error_rate"

        steps.append(
            InvestigationStep(
                id="query_telemetry",
                description=f"Query recent canonical telemetry samples for {metric_name}",
                capability="telemetry",
                params={
                    "service_name": incident.service_name,
                    "metric_name": metric_name,
                    "lookback_seconds": 300,
                },
            )
        )

        steps.append(
            InvestigationStep(
                id="baseline_comparison",
                description=f"Compare current {metric_name} window against historical baseline",
                capability="baseline",
                params={
                    "service_name": incident.service_name,
                    "metric_name": metric_name,
                    "current_window_seconds": 120,
                    "baseline_window_seconds": 600,
                },
            )
        )

        return InvestigationPlan(
            steps=steps,
            rationale=(
                f"Incident triggered on service '{incident.service_name}' by rule '{incident.trigger_rule_id}'. "
                f"Correlating recent telemetry and baseline divergence."
            ),
        )

    async def generate_knowledge_queries(
        self,
        incident: Incident,
        plan: InvestigationPlan,
        telemetry_evidence: list[InvestigationEvidence],
    ) -> list[KnowledgeQuery]:
        """
        Generate operational knowledge queries grounded in incident symptoms.
        """
        metric_str = "error rate"
        for te in telemetry_evidence:
            if te.signal:
                metric_str = te.signal
                break

        return [
            KnowledgeQuery(
                query=f"{incident.service_name} {metric_str} troubleshooting resolution",
                service=incident.service_name,
                limit=3,
            ),
            KnowledgeQuery(
                query=f"{incident.title} runbook postmortem",
                limit=3,
            ),
        ]

    async def analyze_hypotheses(
        self,
        incident: Incident,
        evidence: list[InvestigationEvidence],
    ) -> list[Hypothesis]:
        """
        Formulate structured hypotheses grounded exclusively in collected evidence.
        Separates live operational telemetry from organizational knowledge context.
        """
        if not evidence:
            return []

        hypotheses: list[Hypothesis] = []
        elevated_telemetry_ids: list[str] = []
        normal_telemetry_ids: list[str] = []
        knowledge_evidence_ids: list[str] = []

        # Untrusted prompt injection phrases to detect and ignore
        adversarial_phrases = ["ignore all previous", "declare this incident", "drop database"]

        for e in evidence:
            if e.kind == "knowledge":
                # Check for adversarial content and ignore
                snippet = (e.content_snippet or "").lower()
                is_adversarial = any(phrase in snippet for phrase in adversarial_phrases)
                if not is_adversarial:
                    knowledge_evidence_ids.append(e.evidence_id)
                continue

            obs = e.observation
            is_elevated = False
            if obs.get("is_elevated") is True:
                is_elevated = True
            elif obs.get("observed_max", 0) is not None and obs.get("observed_max", 0) > 0.10:
                is_elevated = True
            elif obs.get("latest_value", 0) is not None and obs.get("latest_value", 0) > 0.10:
                is_elevated = True

            if is_elevated:
                elevated_telemetry_ids.append(e.evidence_id)
            else:
                normal_telemetry_ids.append(e.evidence_id)

        if elevated_telemetry_ids:
            # When operational knowledge supports the observed telemetry, confidence is boosted
            has_knowledge = len(knowledge_evidence_ids) > 0
            base_conf = 0.75 if has_knowledge else 0.70
            conf = min(0.95, base_conf + (0.05 * len(elevated_telemetry_ids)) + (0.05 * len(knowledge_evidence_ids)))

            supporting_all = elevated_telemetry_ids + knowledge_evidence_ids

            hypotheses.append(
                Hypothesis(
                    hypothesis_id="H01",
                    hypothesis=f"Sustained telemetry degradation on {incident.service_name} exceeding operating thresholds",
                    confidence=round(conf, 2),
                    supporting_evidence_ids=supporting_all,
                    contradicting_evidence_ids=normal_telemetry_ids,
                )
            )
        else:
            # Weak or insufficient evidence
            hypotheses.append(
                Hypothesis(
                    hypothesis_id="H02",
                    hypothesis=f"Transient anomaly or insufficient telemetry signal on {incident.service_name}",
                    confidence=0.45,
                    supporting_evidence_ids=[e.evidence_id for e in evidence],
                    contradicting_evidence_ids=[],
                )
            )

        return hypotheses

    async def generate_diagnosis(
        self,
        incident: Incident,
        evidence: list[InvestigationEvidence],
        hypothesis: Hypothesis,
    ) -> Diagnosis:
        """
        Generate structured diagnosis referencing supporting evidence IDs.
        Separates observed operational evidence from known organizational knowledge.
        """
        supporting_details: list[str] = []
        evidence_by_id = {e.evidence_id: e for e in evidence}
        observed_ids: list[str] = []
        knowledge_ids: list[str] = []
        recommended_actions: list[str] = []

        for eid in hypothesis.supporting_evidence_ids:
            if eid in evidence_by_id:
                item = evidence_by_id[eid]
                if item.kind == "knowledge":
                    knowledge_ids.append(eid)
                    doc_title = item.observation.get("title") or item.document_id or "runbook"
                    supporting_details.append(f"Knowledge [{eid}]: Reference document '{doc_title}'")
                    # Extract suggested actions from runbook if present
                    if "connection" in str(item.content_snippet).lower():
                        recommended_actions.append("Check active connection pool status and idle connections")
                    elif "rollback" in str(item.content_snippet).lower():
                        recommended_actions.append("Verify recent canary deployment diff and prepare rollback")
                else:
                    observed_ids.append(eid)
                    obs = item.observation
                    max_val = obs.get("observed_max") or obs.get("latest_value") or obs.get("current_avg")
                    base_val = obs.get("baseline_avg")
                    if base_val is not None and max_val is not None:
                        supporting_details.append(
                            f"Evidence [{eid}]: {item.signal} rose to {max_val} (baseline: {base_val})"
                        )
                    elif max_val is not None:
                        supporting_details.append(
                            f"Evidence [{eid}]: {item.signal} observed at {max_val}"
                        )
                    else:
                        supporting_details.append(f"Evidence [{eid}]: {item.relevance}")

        if not recommended_actions:
            recommended_actions = [
                f"Inspect container application logs for '{incident.service_name}'",
                "Verify resource limits and connection pools",
                "Check for recent release or configuration changes",
            ]

        explanation = (
            f"Investigation of incident '{incident.incident_id}' on service '{incident.service_name}' "
            f"confirms root cause: {hypothesis.hypothesis}. "
            f"Details: {'; '.join(supporting_details)}."
        )

        return Diagnosis(
            root_cause=hypothesis.hypothesis,
            confidence=hypothesis.confidence,
            supporting_evidence=hypothesis.supporting_evidence_ids,
            contradicting_evidence=hypothesis.contradicting_evidence_ids,
            explanation=explanation,
            recommended_actions=recommended_actions,
            observed_evidence=observed_ids,
            knowledge_evidence=knowledge_ids,
            reasoning_summary=f"Correlated {len(observed_ids)} telemetry signals with {len(knowledge_ids)} knowledge documents.",
            uncertainties=["Transient network spikes cannot be fully ruled out without packet capture"] if not knowledge_ids else [],
        )

    async def verify_diagnosis(
        self,
        incident: Incident,
        evidence: list[InvestigationEvidence],
        diagnosis: Diagnosis,
    ) -> VerificationResult:
        """
        Verify that diagnosis meets confidence threshold and references valid evidence.
        Validates both observed telemetry and organizational knowledge citations.
        """
        evidence_ids = {e.evidence_id for e in evidence}

        # Verification check 1: Must have supporting evidence
        if not diagnosis.supporting_evidence:
            return VerificationResult(
                is_verified=False,
                confidence=0.0,
                reason="Diagnosis contains no supporting evidence references.",
                missing_evidence=["supporting_evidence"],
            )

        # Verification check 2: All referenced supporting evidence IDs must exist
        invalid_ids = [eid for eid in diagnosis.supporting_evidence if eid not in evidence_ids]
        if invalid_ids:
            return VerificationResult(
                is_verified=False,
                confidence=0.0,
                reason=f"Diagnosis references non-existent evidence IDs: {invalid_ids}.",
                missing_evidence=invalid_ids,
            )

        # Verification check 3: Cited observed_evidence must exist in evidence
        invalid_obs = [eid for eid in diagnosis.observed_evidence if eid not in evidence_ids]
        if invalid_obs:
            return VerificationResult(
                is_verified=False,
                confidence=0.0,
                reason=f"Diagnosis references invalid observed evidence IDs: {invalid_obs}.",
                missing_evidence=invalid_obs,
            )

        # Verification check 4: Cited knowledge_evidence must exist in evidence
        invalid_k = [eid for eid in diagnosis.knowledge_evidence if eid not in evidence_ids]
        if invalid_k:
            return VerificationResult(
                is_verified=False,
                confidence=0.0,
                reason=f"Diagnosis references invalid knowledge evidence IDs: {invalid_k}.",
                missing_evidence=invalid_k,
            )

        # Verification check 5: Confidence threshold
        if diagnosis.confidence < self._confidence_threshold:
            return VerificationResult(
                is_verified=False,
                confidence=diagnosis.confidence,
                reason=(
                    f"Confidence {diagnosis.confidence:.2f} is below verification threshold "
                    f"{self._confidence_threshold:.2f}."
                ),
                missing_evidence=["additional_telemetry_correlation"],
            )

        return VerificationResult(
            is_verified=True,
            confidence=diagnosis.confidence,
            reason="Diagnosis is verified with valid supporting evidence exceeding confidence threshold.",
        )

