"""
Claim Grounding Evaluator Protocol and Implementations.

Defines:
1. `ClaimGroundingEvaluator` Protocol
2. `HeuristicClaimGroundingEvaluator`: fast, offline, deterministic evaluator verifying:
   - Citation Reference Validity (are cited IDs present in retrieved evidence?)
   - Lexical and Structural Evidence Support
   - Causal Connection Support (requires multi-point temporal/event evidence)
   - Contradiction Detection
3. `ExternalJudgeClaimGroundingEvaluator`: configuration-aware wrapper for external LLM judges
   (e.g., Claude 3.5, GPT-4o) with provenance recording.
"""
from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

from sentinelops.domain.models.incident import EvidenceItem
from sentinelops.domain.models.investigation import InvestigationEvidence
from sentinelops.evals.grounding.models import (
    CausalLabel,
    Claim,
    ClaimType,
    GroundingLabel,
    GroundingResult,
)


@runtime_checkable
class ClaimGroundingEvaluator(Protocol):
    """Protocol for evaluating atomic diagnostic claims against operational evidence."""

    def evaluate(
        self,
        claim: Claim,
        evidence: list[EvidenceItem | InvestigationEvidence | dict[str, Any]],
    ) -> GroundingResult:
        """Evaluate whether operational evidence supports or contradicts the claim."""
        ...


class HeuristicClaimGroundingEvaluator:
    """
    Offline, deterministic rule-based evaluator for claim grounding.
    Evaluates:
    - citation_reference_validity
    - evidence token overlap
    - contradictory directional indicators
    - causal linkage criteria
    """

    def __init__(self, token_overlap_threshold: float = 0.25) -> None:
        self.token_overlap_threshold = token_overlap_threshold
        self.evaluator_name = "heuristic_structural_grounding_evaluator"

    def evaluate(
        self,
        claim: Claim,
        evidence: list[EvidenceItem | InvestigationEvidence | dict[str, Any]],
    ) -> GroundingResult:
        evidence_by_id: dict[str, str] = {}
        for ev in evidence:
            ev_id = getattr(ev, "evidence_id", None) or (ev.get("evidence_id") if isinstance(ev, dict) else None)
            desc = getattr(ev, "description", None) or (ev.get("description") if isinstance(ev, dict) else "")
            content = getattr(ev, "content", None) or (ev.get("content") if isinstance(ev, dict) else "")
            text = f"{desc} {content}".strip()
            if ev_id:
                evidence_by_id[ev_id] = text

        # 1. Citation Reference Validity
        cited_ids = claim.cited_evidence_ids
        if not cited_ids:
            return GroundingResult(
                claim_id=claim.claim_id,
                incident_id=claim.incident_id,
                claim_text=claim.claim_text,
                claim_type=claim.claim_type,
                cited_evidence_ids=[],
                label=GroundingLabel.UNSUPPORTED,
                causal_label=CausalLabel.CAUSALITY_NOT_ESTABLISHED if claim.claim_type == ClaimType.CAUSAL else None,
                confidence=1.0,
                evaluator_name=self.evaluator_name,
                citation_valid=False,
                reason="No evidence cited for claim.",
            )

        valid_citations = [cid for cid in cited_ids if cid in evidence_by_id]
        if not valid_citations:
            return GroundingResult(
                claim_id=claim.claim_id,
                incident_id=claim.incident_id,
                claim_text=claim.claim_text,
                claim_type=claim.claim_type,
                cited_evidence_ids=cited_ids,
                label=GroundingLabel.UNSUPPORTED,
                causal_label=CausalLabel.CAUSALITY_NOT_ESTABLISHED if claim.claim_type == ClaimType.CAUSAL else None,
                confidence=1.0,
                evaluator_name=self.evaluator_name,
                citation_valid=False,
                reason=f"All cited evidence IDs {cited_ids} are missing from collected evidence.",
            )

        # 2. Extract cited text corpus
        cited_text = " ".join(evidence_by_id[cid] for cid in valid_citations).lower()

        # Tokenize claim keywords (excluding stop words)
        stop_words = {"the", "a", "an", "is", "was", "were", "and", "or", "in", "on", "at", "to", "for", "with", "of", "by"}
        claim_tokens = {w for w in re.findall(r"\b[a-zA-Z0-9_\-\.]+\b", claim.claim_text.lower()) if w not in stop_words}

        if not claim_tokens:
            overlap = 1.0
        else:
            hits = sum(1 for tok in claim_tokens if tok in cited_text)
            overlap = hits / len(claim_tokens)

        # 3. Check for contradiction indicators
        is_contradicted = False
        if "normal" in claim.claim_text.lower() and ("exceeded" in cited_text or "spike" in cited_text or "saturation" in cited_text):
            is_contradicted = True
        elif "recovered" in claim.claim_text.lower() and ("failing" in cited_text or "elevated" in cited_text):
            is_contradicted = True

        if is_contradicted:
            return GroundingResult(
                claim_id=claim.claim_id,
                incident_id=claim.incident_id,
                claim_text=claim.claim_text,
                claim_type=claim.claim_type,
                cited_evidence_ids=valid_citations,
                label=GroundingLabel.CONTRADICTED,
                causal_label=CausalLabel.CAUSALITY_NOT_ESTABLISHED if claim.claim_type == ClaimType.CAUSAL else None,
                confidence=0.90,
                evaluator_name=self.evaluator_name,
                citation_valid=True,
                reason="Cited evidence explicitly contradicts claim polarity/status.",
            )

        # 4. Classify factual support
        if overlap >= self.token_overlap_threshold:
            fact_label = GroundingLabel.SUPPORTED
        elif overlap > 0.05:
            fact_label = GroundingLabel.PARTIALLY_SUPPORTED
        else:
            fact_label = GroundingLabel.UNSUPPORTED

        # 5. Causal evaluation
        causal_label = None
        if claim.claim_type == ClaimType.CAUSAL:
            # Causal support requires at least two distinct valid evidence items or explicit causal phrasing in runbook/release
            if len(valid_citations) >= 2 and fact_label in (GroundingLabel.SUPPORTED, GroundingLabel.PARTIALLY_SUPPORTED):
                causal_label = CausalLabel.CAUSALLY_SUPPORTED
            elif "cause" in cited_text or "leads to" in cited_text or "trigger" in cited_text:
                causal_label = CausalLabel.CAUSALLY_SUPPORTED
            else:
                causal_label = CausalLabel.CAUSALITY_NOT_ESTABLISHED

        reason = (
            f"Citation reference valid ({len(valid_citations)}/{len(cited_ids)}). "
            f"Evidence keyword overlap: {overlap:.1%}. "
            f"Causal status: {causal_label.value if causal_label else 'N/A'}."
        )

        return GroundingResult(
            claim_id=claim.claim_id,
            incident_id=claim.incident_id,
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            cited_evidence_ids=valid_citations,
            label=fact_label,
            causal_label=causal_label,
            confidence=0.85,
            evaluator_name=self.evaluator_name,
            citation_valid=len(valid_citations) == len(cited_ids),
            reason=reason,
            metadata={"token_overlap": round(overlap, 4)},
        )


class ExternalJudgeClaimGroundingEvaluator:
    """
    Evaluator that leverages an external LLM judge.
    If no external API key is provided, explicitly records that semantic entailment is NOT EVALUATED.
    """

    def __init__(
        self,
        judge_provider: str = "anthropic",
        judge_model: str = "claude-3-5-sonnet-20241022",
        judge_version: str = "v1.0",
        prompt_version: str = "claim_entailment_v1",
        temperature: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        self.judge_provider = judge_provider
        self.judge_model = judge_model
        self.judge_version = judge_version
        self.prompt_version = prompt_version
        self.temperature = temperature
        self.api_key = api_key
        self.evaluator_name = f"external_judge_{judge_provider}_{judge_model}"

    def evaluate(
        self,
        claim: Claim,
        evidence: list[EvidenceItem | InvestigationEvidence | dict[str, Any]],
    ) -> GroundingResult:
        if not self.api_key:
            # Fall back to heuristic evaluator while explicitly tagging that semantic NLI is unconfigured
            fallback = HeuristicClaimGroundingEvaluator()
            res = fallback.evaluate(claim, evidence)
            return GroundingResult(
                claim_id=res.claim_id,
                incident_id=res.incident_id,
                claim_text=res.claim_text,
                claim_type=res.claim_type,
                cited_evidence_ids=res.cited_evidence_ids,
                label=res.label,
                causal_label=res.causal_label,
                confidence=res.confidence,
                evaluator_name=f"{self.evaluator_name}_fallback_heuristic",
                citation_valid=res.citation_valid,
                reason=f"Offline fallback (no API key configured): {res.reason}",
                metadata={
                    "semantic_nli_entailment": "NOT EVALUATED",
                    "judge_provider": self.judge_provider,
                    "judge_model": self.judge_model,
                },
            )

        raise NotImplementedError("Live external LLM judge requires active API egress and credentials.")
