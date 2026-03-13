"""Accuracy scoring for fact-checked articles."""

from __future__ import annotations

from app.schemas.fact_check import VerifiedClaim

CONFIDENCE_WEIGHTS = {
    "high": 1.0,
    "medium": 0.7,
    "low": 0.4,
}


def calculate_accuracy_score(verified_claims: list[VerifiedClaim]) -> float | None:
    """Calculate accuracy score from verified claims.

    Formula: sum(confirmed_weight) / sum(total_weight) for non-unverifiable claims.
    Returns None if no verifiable claims exist.
    """
    confirmed_weight = 0.0
    total_weight = 0.0

    for claim in verified_claims:
        if claim.verdict == "unverifiable":
            continue
        weight = CONFIDENCE_WEIGHTS.get(claim.confidence, 0.4)
        total_weight += weight
        if claim.verdict == "confirmed":
            confirmed_weight += weight

    if total_weight == 0:
        return None

    return round(confirmed_weight / total_weight, 3)
