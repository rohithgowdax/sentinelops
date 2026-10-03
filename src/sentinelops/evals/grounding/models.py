"""
Domain models for Claim-Level Semantic Grounding Evaluation.

Decomposes agent diagnoses into atomic factual and causal claims, and classifies
grounding support against cited operational evidence.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ClaimType(str, Enum):
    """Classification of claim nature."""

    FACTUAL = "factual"
    CAUSAL = "causal"


class GroundingLabel(str, Enum):
    """Grounding classification for factual assertions."""

    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"


class CausalLabel(str, Enum):
    """Grounding classification for causal link assertions."""

    CAUSALLY_SUPPORTED = "CAUSALLY_SUPPORTED"
    CAUSALITY_NOT_ESTABLISHED = "CAUSALITY_NOT_ESTABLISHED"


class Claim(BaseModel):
    """An atomic factual or causal claim extracted from an agent diagnosis."""

    claim_id: str
    incident_id: str
    claim_text: str
    claim_type: ClaimType = ClaimType.FACTUAL
    cited_evidence_ids: list[str] = Field(default_factory=list)
    source_field: str = "root_cause"  # "root_cause" or "explanation"


class GroundingResult(BaseModel):
    """Evaluation result for an individual claim."""

    claim_id: str
    incident_id: str
    claim_text: str
    claim_type: ClaimType
    cited_evidence_ids: list[str]
    label: GroundingLabel
    causal_label: CausalLabel | None = None
    confidence: float = 1.0
    evaluator_name: str
    citation_valid: bool
    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClaimDecomposition(BaseModel):
    """Set of atomic claims extracted from an incident diagnosis."""

    incident_id: str
    original_text: str
    claims: list[Claim] = Field(default_factory=list)
