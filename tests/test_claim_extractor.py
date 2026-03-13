"""Tests for the claim extraction service (Pass 1)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.fact_check import ClaimExtractionResult, ExtractedClaim
from app.services.claim_extractor import (
    extract_claims,
    post_validate_claims,
    truncate_article,
)


def test_truncate_short_article():
    """Short articles are not truncated."""
    text = "word " * 100
    result, was_truncated = truncate_article(text.strip(), max_words=3500)
    assert not was_truncated
    assert result == text.strip()


def test_truncate_long_article():
    """Long articles are truncated to max_words."""
    text = "word " * 5000
    result, was_truncated = truncate_article(text.strip(), max_words=3500)
    assert was_truncated
    assert len(result.split()) == 3500


def test_post_validate_filters_short_claims():
    """Claims with short claim_text are filtered out."""
    claims = [
        ExtractedClaim(claim_text="Too short", claim_type="factual_assertion", original_quote="x"),
        ExtractedClaim(claim_text="This is a valid claim with enough text", claim_type="factual_assertion", original_quote="y"),
    ]
    result = post_validate_claims(claims)
    assert len(result) == 1
    assert result[0].claim_text == "This is a valid claim with enough text"


def test_post_validate_deduplicates():
    """Duplicate claims (case-insensitive) are deduplicated."""
    claims = [
        ExtractedClaim(claim_text="The president signed the bill", claim_type="factual_assertion", original_quote="a"),
        ExtractedClaim(claim_text="the president signed the bill", claim_type="attribution", original_quote="b"),
    ]
    result = post_validate_claims(claims)
    assert len(result) == 1


MOCK_LLM_RESPONSE = json.dumps({
    "claims": [
        {
            "claim_text": "The company reported $5 billion in revenue",
            "claim_type": "statistic",
            "original_quote": "The company reported $5 billion in revenue for Q3",
        },
        {
            "claim_text": "CEO John Smith called it a record quarter",
            "claim_type": "attribution",
            "original_quote": 'CEO John Smith called it "a record quarter"',
        },
    ],
    "cluster_summary": {
        "title": "Company Reports Q3 Revenue",
        "summary": "The company announced Q3 financial results showing $5 billion in revenue.",
    },
})


@pytest.mark.asyncio
async def test_valid_extraction():
    """Successfully extracts claims from article text."""
    with patch(
        "app.services.claim_extractor.call_llm_structured",
        new_callable=AsyncMock,
        return_value={"content": MOCK_LLM_RESPONSE, "eval_count": 100, "total_duration": 5000},
    ):
        result = await extract_claims(
            article_text="Some article text about the company.",
            source_name="Reuters",
            trust_tier="high",
            title="Company Q3 Results",
            published_at="2026-03-13",
            ollama_url="http://localhost:11434",
        )

    assert isinstance(result, ClaimExtractionResult)
    assert len(result.claims) == 2
    assert result.claims[0].claim_type == "statistic"
    assert result.cluster_summary.title == "Company Reports Q3 Revenue"


@pytest.mark.asyncio
async def test_ollama_error_propagates():
    """RuntimeError from Ollama client propagates to caller."""
    with patch(
        "app.services.claim_extractor.call_llm_structured",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Ollama down"),
    ):
        with pytest.raises(RuntimeError, match="Ollama down"):
            await extract_claims(
                article_text="Some text",
                source_name="AP",
                trust_tier="high",
                title="Test",
                published_at="2026-03-13",
                ollama_url="http://localhost:11434",
            )
