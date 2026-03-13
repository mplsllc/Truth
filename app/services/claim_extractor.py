"""Pass 1: Extract verifiable claims from article text using Ollama LLM."""

from __future__ import annotations

import structlog

from app.schemas.fact_check import ClaimExtractionResult, ExtractedClaim
from app.services.ollama_client import call_ollama_structured

log = structlog.get_logger()

MAX_ARTICLE_WORDS = 3500

EXTRACTION_SYSTEM_PROMPT = """\
You are a fact-check analyst. Your job is to extract every verifiable claim from a news article.

Extract ALL checkable claims including:
- Factual assertions (events, dates, numbers, names)
- Attributions (who said what)
- Statistics and data points
- Characterizations (descriptions of people, organizations, events)
- Framing (how an issue is presented, what context is included or omitted)
- Cherry-picked stats (selective use of data)
- Missing context (important facts omitted)

For each claim, provide:
- claim_text: A clear, standalone statement of the claim
- claim_type: One of: factual_assertion, attribution, statistic, characterization, framing, missing_context
- original_quote: The exact text from the article that contains this claim

Also generate a neutral cluster summary:
- title: A neutral, factual headline (no outlet's framing)
- summary: 2-3 sentence neutral summary of the story

Respond with valid JSON matching the required schema."""

EXTRACTION_USER_TEMPLATE = """\
Article from {source_name} ({trust_tier} trust):
Title: {title}
Published: {published_at}

{article_text}

Extract all verifiable claims from this article."""


def truncate_article(text: str, max_words: int = MAX_ARTICLE_WORDS) -> tuple[str, bool]:
    """Truncate article to max_words. Returns (text, was_truncated)."""
    words = text.split()
    if len(words) <= max_words:
        return text, False
    return " ".join(words[:max_words]), True


def post_validate_claims(claims: list[ExtractedClaim]) -> list[ExtractedClaim]:
    """Filter short claims and deduplicate by claim_text."""
    seen: set[str] = set()
    result: list[ExtractedClaim] = []
    for claim in claims:
        if len(claim.claim_text) < 10:
            continue
        key = claim.claim_text.lower().strip()
        if key in seen:
            continue
        seen.add(key)
        result.append(claim)
    return result


async def extract_claims(
    article_text: str,
    source_name: str,
    trust_tier: str,
    title: str,
    published_at: str,
    ollama_url: str,
) -> ClaimExtractionResult:
    """Extract verifiable claims from article text via Ollama LLM.

    Returns ClaimExtractionResult with validated claims and cluster summary.
    Raises RuntimeError on Ollama failure, ValidationError on parse failure.
    """
    text, was_truncated = truncate_article(article_text)

    if was_truncated:
        await log.awarn(
            "article_truncated",
            title=title,
            original_words=len(article_text.split()),
            truncated_to=MAX_ARTICLE_WORDS,
        )

    user_message = EXTRACTION_USER_TEMPLATE.format(
        source_name=source_name,
        trust_tier=trust_tier,
        title=title,
        published_at=published_at,
        article_text=text,
    )

    messages = [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    result = await call_ollama_structured(
        messages=messages,
        schema_class=ClaimExtractionResult,
        ollama_url=ollama_url,
    )

    parsed = ClaimExtractionResult.model_validate_json(result["content"])
    parsed.claims = post_validate_claims(parsed.claims)

    await log.ainfo(
        "claims_extracted",
        title=title,
        claim_count=len(parsed.claims),
        was_truncated=was_truncated,
        eval_count=result.get("eval_count"),
    )

    return parsed
