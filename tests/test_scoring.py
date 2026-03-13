"""Tests for accuracy scoring module."""

from __future__ import annotations

from app.schemas.fact_check import VerifiedClaim
from app.services.scoring import calculate_accuracy_score


def _claim(verdict: str, confidence: str = "high") -> VerifiedClaim:
    return VerifiedClaim(
        claim_text="test",
        verdict=verdict,
        confidence=confidence,
        reasoning="test",
        supporting_sources=[],
        contradicting_sources=[],
    )


def test_all_confirmed_high_confidence():
    score = calculate_accuracy_score([_claim("confirmed"), _claim("confirmed")])
    assert score == 1.0


def test_all_contradicted():
    score = calculate_accuracy_score([_claim("contradicted"), _claim("contradicted")])
    assert score == 0.0


def test_mixed_verdicts():
    score = calculate_accuracy_score([_claim("confirmed"), _claim("contradicted")])
    assert score == 0.5


def test_unverifiable_excluded():
    score = calculate_accuracy_score([
        _claim("confirmed"),
        _claim("unverifiable"),
        _claim("unverifiable"),
    ])
    assert score == 1.0


def test_all_unverifiable_returns_none():
    score = calculate_accuracy_score([_claim("unverifiable"), _claim("unverifiable")])
    assert score is None


def test_empty_claims_returns_none():
    score = calculate_accuracy_score([])
    assert score is None


def test_confidence_weighting():
    # high confirmed (1.0) + low contradicted (0.4) = 1.0 / 1.4 ≈ 0.714
    score = calculate_accuracy_score([
        _claim("confirmed", "high"),
        _claim("contradicted", "low"),
    ])
    assert score == round(1.0 / 1.4, 3)
