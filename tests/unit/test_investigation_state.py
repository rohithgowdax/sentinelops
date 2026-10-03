"""
Unit tests for SentinelOps AI Investigation domain models and state contracts.
"""
from __future__ import annotations

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from sentinelops.domain.models.investigation import (
    Diagnosis,
    Hypothesis,
    InvestigationEvidence,
    InvestigationPlan,
    InvestigationResult,
    InvestigationStatus,
    InvestigationStep,
    VerificationResult,
)


class TestInvestigationModels:
    """Test suite verifying investigation domain models and typed validation rules."""

    def test_investigation_status_values(self) -> None:
        """Verify lifecycle enum status string mappings."""
        assert InvestigationStatus.INVESTIGATING.value == "investigating"
        assert InvestigationStatus.DIAGNOSED.value == "diagnosed"
        assert InvestigationStatus.INSUFFICIENT_EVIDENCE.value == "insufficient_evidence"
        assert InvestigationStatus.INVESTIGATION_FAILED.value == "investigation_failed"

    def test_investigation_step_and_plan(self) -> None:
        """Verify structured InvestigationPlan serialization."""
        step1 = InvestigationStep(
            id="query_error_rate",
            description="Fetch recent error rates for payments service",
            capability="telemetry",
            params={"metric_name": "http.error_rate"},
        )
        step2 = InvestigationStep(
            id="compare_error_rate_baseline",
            description="Compare error rates with prior 1h baseline",
            capability="baseline",
            params={"metric_name": "http.error_rate"},
        )
        plan = InvestigationPlan(
            steps=[step1, step2],
            rationale="Evaluate whether error spikes exceed historical averages.",
        )
        assert len(plan.steps) == 2
        assert plan.steps[0].id == "query_error_rate"
        assert plan.steps[1].capability == "baseline"

        # Roundtrip JSON
        dumped = plan.model_dump_json()
        loaded = InvestigationPlan.model_validate_json(dumped)
        assert len(loaded.steps) == 2
        assert loaded.rationale == plan.rationale

    def test_investigation_evidence_auto_id(self) -> None:
        """Verify unique evidence IDs start with 'E'."""
        ev1 = InvestigationEvidence(
            incident_id="INC-001",
            source_type="telemetry",
            source_ref="http.error_rate",
            resource="payments-service",
            signal="http.error_rate",
            observation={"observed_max": 0.25, "sample_count": 10},
        )
        ev2 = InvestigationEvidence(
            incident_id="INC-001",
            source_type="baseline_comparison",
            source_ref="http.error_rate",
            resource="payments-service",
            signal="http.error_rate",
            observation={"baseline": 0.02, "current_avg": 0.22, "ratio": 11.0},
        )
        assert ev1.evidence_id.startswith("E")
        assert ev2.evidence_id.startswith("E")
        assert ev1.evidence_id != ev2.evidence_id
        assert ev1.incident_id == "INC-001"

    def test_hypothesis_confidence_validation(self) -> None:
        """Verify confidence is constrained between 0.0 and 1.0."""
        hyp = Hypothesis(
            hypothesis="Downstream latency causing timeout cascades",
            confidence=0.85,
            supporting_evidence_ids=["E01", "E02"],
        )
        assert hyp.confidence == 0.85

        with pytest.raises(ValidationError):
            Hypothesis(hypothesis="Invalid", confidence=1.5)

        with pytest.raises(ValidationError):
            Hypothesis(hypothesis="Invalid", confidence=-0.1)

    def test_diagnosis_evidence_linkage(self) -> None:
        """Verify diagnosis contains supporting evidence IDs and recommended actions."""
        diagnosis = Diagnosis(
            root_cause="Database connection pool exhaustion leading to HTTP 500 error spike",
            confidence=0.92,
            supporting_evidence=["E12345", "E67890"],
            contradicting_evidence=[],
            explanation="Error rate climbed to 25% coinciding with 10x baseline deviation.",
            recommended_actions=["Increase max pool size", "Restart stale workers"],
        )
        assert len(diagnosis.supporting_evidence) == 2
        assert "E12345" in diagnosis.supporting_evidence
        assert len(diagnosis.recommended_actions) == 2

    def test_verification_result(self) -> None:
        """Verify VerificationResult validation."""
        vr_success = VerificationResult(
            is_verified=True,
            confidence=0.90,
            reason="Clear signal anomaly verified against baseline.",
        )
        assert vr_success.is_verified is True

        vr_fail = VerificationResult(
            is_verified=False,
            confidence=0.30,
            reason="Sample count too low; contradictory logs.",
            missing_evidence=["error_logs"],
            contradictions_found=["database CPU normal"],
        )
        assert vr_fail.is_verified is False
        assert len(vr_fail.missing_evidence) == 1

    def test_investigation_result_roundtrip(self) -> None:
        """Verify complete InvestigationResult serialization roundtrip."""
        diag = Diagnosis(
            root_cause="Service error surge",
            confidence=0.88,
            supporting_evidence=["E001"],
            explanation="Elevated failure metrics.",
            recommended_actions=["Check downstream dependency"],
        )
        ev = InvestigationEvidence(
            evidence_id="E001",
            incident_id="INC-999",
            source_type="telemetry",
            source_ref="http.error_rate",
            resource="auth-service",
            signal="http.error_rate",
            observation={"observed_max": 0.40},
        )
        step = InvestigationStep(
            id="step1",
            description="Collect error rates",
            capability="telemetry",
        )
        result = InvestigationResult(
            incident_id="INC-999",
            status=InvestigationStatus.DIAGNOSED,
            diagnosis=diag,
            confidence=0.88,
            supporting_evidence=[ev],
            investigation_steps=[step],
            tool_calls_summary=[{"tool": "query_recent_telemetry", "count": 5}],
            duration_seconds=1.23,
            iteration_count=1,
            completed_at=datetime.now(tz=timezone.utc),
        )

        json_str = result.model_dump_json()
        reconstructed = InvestigationResult.model_validate_json(json_str)
        assert reconstructed.incident_id == "INC-999"
        assert reconstructed.status == InvestigationStatus.DIAGNOSED
        assert reconstructed.diagnosis is not None
        assert reconstructed.diagnosis.root_cause == "Service error surge"
        assert len(reconstructed.supporting_evidence) == 1
        assert reconstructed.supporting_evidence[0].evidence_id == "E001"
