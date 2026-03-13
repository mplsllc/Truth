"""Tests for claim verification service (Pass 2)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.fact_check import ClaimVerificationResult, ExtractedClaim
from app.services.claim_verifier import format_claims, format_evidence, verify_claims
from app.services.evidence_gatherer import EvidenceBundle, EvidenceItem


def test_format_claims():
    claims = [
        ExtractedClaim(claim_text="Claim A", claim_type="statistic", original_quote="x"),
        ExtractedClaim(claim_text="Claim B", claim_type="attribution", original_quote="y"),
    ]
    result = format_claims(claims)
    assert "1. [statistic] Claim A" in result
    assert "2. [attribution] Claim B" in result


def test_format_evidence_with_items():
    bundle = EvidenceBundle(
        items=[
            EvidenceItem(
                source_name="Reuters",
                source_url="http://example.com",
                text="Some evidence text",
                trust_tier="high",
                tier_source="cluster",
            )
        ],
        cluster_count=1,
    )
    result = format_evidence(bundle)
    assert "Reuters" in result
    assert "high trust" in result
    assert "Some evidence text" in result


def test_format_evidence_empty():
    bundle = EvidenceBundle()
    result = format_evidence(bundle)
    assert "No evidence available" in result


MOCK_VERIFICATION_RESPONSE = json.dumps({
    "verified_claims": [
        {
            "claim_text": "Test claim",
            "verdict": "confirmed",
            "confidence": "high",
            "reasoning": "Multiple sources agree.",
            "supporting_sources": ["Reuters"],
            "contradicting_sources": [],
        }
    ]
})


@pytest.mark.asyncio
async def test_verify_claims_success():
    claims = [
        ExtractedClaim(claim_text="Test claim", claim_type="factual_assertion", original_quote="x"),
    ]
    evidence = EvidenceBundle(
        items=[
            EvidenceItem("Reuters", "http://r.com", "evidence", "high", "cluster")
        ],
        cluster_count=1,
    )

    with patch(
        "app.services.claim_verifier.call_ollama_structured",
        new_callable=AsyncMock,
        return_value={"content": MOCK_VERIFICATION_RESPONSE, "eval_count": 50},
    ):
        result = await verify_claims(claims, evidence, "http://localhost:11434")

    assert isinstance(result, ClaimVerificationResult)
    assert len(result.verified_claims) == 1
    assert result.verified_claims[0].verdict == "confirmed"


@pytest.mark.asyncio
async def test_verify_empty_claims():
    result = await verify_claims([], EvidenceBundle(), "http://localhost:11434")
    assert result.verified_claims == []
