"""
Atomic Claim Decomposer for SentinelOps Diagnoses.

Parses unstructured diagnostic root cause and explanation texts into distinct,
atomic factual and causal claims.
"""
from __future__ import annotations

import re
from sentinelops.evals.grounding.models import Claim, ClaimDecomposition, ClaimType

CAUSAL_CONNECTIVES = [
    r"\bcaused\b",
    r"\bcauses\b",
    r"\bcausing\b",
    r"\bled to\b",
    r"\bleading to\b",
    r"\bresulted in\b",
    r"\bresulting in\b",
    r"\bdue to\b",
    r"\bbecause\b",
    r"\btriggered\b",
    r"\btriggering\b",
    r"\binduced\b",
]

CAUSAL_REGEX = re.compile("|".join(CAUSAL_CONNECTIVES), re.IGNORECASE)


def decompose_diagnosis_text(
    incident_id: str,
    root_cause_text: str,
    explanation_text: str = "",
    cited_evidence_ids: list[str] | None = None,
) -> ClaimDecomposition:
    """
    Decompose diagnosis root cause and explanation into atomic claims.
    Identifies factual vs causal assertions based on causal connectives.
    """
    evidence_ids = cited_evidence_ids or []
    full_text = f"{root_cause_text.strip()}. {explanation_text.strip()}".strip()
    claims: list[Claim] = []
    claim_idx = 1

    # Split text into sentences
    raw_sentences = re.split(r"[.!?]+(?:\s+|$)", full_text)
    for sent in raw_sentences:
        sent_clean = sent.strip()
        if not sent_clean or len(sent_clean.split()) < 3:
            continue

        # Check for causal clauses
        if CAUSAL_REGEX.search(sent_clean):
            # Split into sub-clauses on causal markers or commas where feasible
            clauses = re.split(r"[,;]+", sent_clean)
            for clause in clauses:
                c_clean = clause.strip()
                if not c_clean or len(c_clean.split()) < 2:
                    continue
                is_causal = bool(CAUSAL_REGEX.search(c_clean))
                claim = Claim(
                    claim_id=f"{incident_id}-C{claim_idx:02d}",
                    incident_id=incident_id,
                    claim_text=c_clean,
                    claim_type=ClaimType.CAUSAL if is_causal else ClaimType.FACTUAL,
                    cited_evidence_ids=evidence_ids,
                    source_field="root_cause" if sent_clean in root_cause_text else "explanation",
                )
                claims.append(claim)
                claim_idx += 1
        else:
            claim = Claim(
                claim_id=f"{incident_id}-C{claim_idx:02d}",
                incident_id=incident_id,
                claim_text=sent_clean,
                claim_type=ClaimType.FACTUAL,
                cited_evidence_ids=evidence_ids,
                source_field="root_cause" if sent_clean in root_cause_text else "explanation",
            )
            claims.append(claim)
            claim_idx += 1

    return ClaimDecomposition(
        incident_id=incident_id,
        original_text=full_text,
        claims=claims,
    )
