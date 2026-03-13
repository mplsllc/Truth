"""Fact-check orchestrator: picks articles, runs full pipeline, updates database."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.claim import Claim
from app.models.enums import FactCheckStatus
from app.models.feed import Feed
from app.services.claim_extractor import extract_claims
from app.services.claim_verifier import verify_claims
from app.services.evidence_gatherer import gather_evidence
from app.services.scoring import calculate_accuracy_score

log = structlog.get_logger()


async def age_out_pending(
    session: AsyncSession,
    max_age_hours: int = 24,
) -> int:
    """Mark PENDING articles older than max_age_hours as EXPIRED.

    Returns count of expired articles.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    result = await session.execute(
        update(Article)
        .where(
            Article.fact_check_status == FactCheckStatus.PENDING,
            Article.created_at < cutoff,
        )
        .values(fact_check_status=FactCheckStatus.EXPIRED)
    )
    count = result.rowcount
    if count > 0:
        await log.ainfo("articles_aged_out", count=count, max_age_hours=max_age_hours)
    await session.flush()
    return count


async def pick_next_article(session: AsyncSession) -> Article | None:
    """Pick the next PENDING article for fact-checking, prioritized by trust tier.

    Uses FOR UPDATE SKIP LOCKED on PostgreSQL for safe concurrent access.
    Falls back to simple select on SQLite.
    """
    # Try PostgreSQL FOR UPDATE SKIP LOCKED first
    try:
        result = await session.execute(
            text("""
                SELECT a.id FROM articles a
                JOIN feeds f ON a.feed_id = f.id
                WHERE a.fact_check_status = :status
                  AND a.content IS NOT NULL
                ORDER BY
                    CASE f.trust_tier
                        WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2
                        WHEN 'low' THEN 3
                        ELSE 4
                    END,
                    a.created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """),
            {"status": FactCheckStatus.PENDING.value},
        )
        row = result.fetchone()
    except Exception:
        # SQLite fallback
        result = await session.execute(
            select(Article.id)
            .join(Feed, Article.feed_id == Feed.id)
            .where(
                Article.fact_check_status == FactCheckStatus.PENDING,
                Article.content.isnot(None),
            )
            .order_by(Article.created_at.asc())
            .limit(1)
        )
        row = result.fetchone()

    if row is None:
        return None

    article = await session.get(Article, row[0])
    if article:
        article.fact_check_status = FactCheckStatus.IN_PROGRESS
        await session.flush()

    return article


async def process_article(
    article: Article,
    session: AsyncSession,
    http_client,
    embed_model: Any,
    ollama_url: str,
) -> bool:
    """Run the full fact-check pipeline on a single article.

    Steps:
    1. Extract claims (Pass 1)
    2. Update cluster title/summary
    3. Gather evidence
    4. Verify claims (Pass 2)
    5. Calculate accuracy score
    6. Store results

    Returns True on success, False on failure.
    """
    log_ctx = log.bind(article_id=article.id, title=article.title)

    try:
        # Get feed info for the article
        feed = await session.get(Feed, article.feed_id)
        source_name = feed.name if feed else "Unknown"
        trust_tier = feed.trust_tier if feed else "medium"

        # Pass 1: Extract claims
        extraction = await extract_claims(
            article_text=article.content,
            source_name=source_name,
            trust_tier=str(trust_tier),
            title=article.title,
            published_at=str(article.published_at or ""),
            ollama_url=ollama_url,
        )

        # Update cluster title/summary if this article's cluster exists
        if article.cluster_id:
            from app.models.cluster import StoryCluster
            cluster = await session.get(StoryCluster, article.cluster_id)
            if cluster and not cluster.title:
                cluster.title = extraction.cluster_summary.title
                cluster.summary = extraction.cluster_summary.summary

        # Gather evidence from all three tiers
        evidence = await gather_evidence(article, session, embed_model, http_client)

        # Pass 2: Verify claims against evidence
        verification = await verify_claims(
            claims=extraction.claims,
            evidence=evidence,
            ollama_url=ollama_url,
        )

        # Calculate accuracy score
        score = calculate_accuracy_score(verification.verified_claims)

        # Store claims in database
        for i, extracted in enumerate(extraction.claims):
            # Match with verification result by index
            verified = (
                verification.verified_claims[i]
                if i < len(verification.verified_claims)
                else None
            )
            claim = Claim(
                article_id=article.id,
                claim_text=extracted.claim_text,
                claim_type=extracted.claim_type,
                original_quote=extracted.original_quote,
                verdict=verified.verdict if verified else None,
                confidence=verified.confidence if verified else None,
                reasoning=verified.reasoning if verified else None,
                supporting_sources=json.dumps(verified.supporting_sources) if verified else None,
                contradicting_sources=json.dumps(verified.contradicting_sources) if verified else None,
            )
            session.add(claim)

        # Update article
        article.accuracy_score = score
        article.fact_checked_at = datetime.now(timezone.utc)
        article.claim_count = len(extraction.claims)
        article.fact_check_status = FactCheckStatus.COMPLETE

        await session.flush()

        await log_ctx.ainfo(
            "fact_check_complete",
            claims=len(extraction.claims),
            accuracy_score=score,
            evidence_items=len(evidence.items),
        )
        return True

    except Exception as e:
        # Expunge pending objects from failed transaction, then mark failure
        session.expire_all()
        article.fact_check_status = FactCheckStatus.FAILED
        article.fact_check_error = str(e)
        await session.flush()

        await log_ctx.aerror("fact_check_failed", error=str(e))
        return False


async def run_fact_check_cycle(
    session: AsyncSession,
    http_client,
    embed_model: Any,
    ollama_url: str,
    max_age_hours: int = 24,
) -> dict:
    """Run one fact-check cycle: age out old articles, process next article.

    Returns stats dict with keys: aged_out, processed, success.
    """
    aged_out = await age_out_pending(session, max_age_hours)

    article = await pick_next_article(session)
    if article is None:
        return {"aged_out": aged_out, "processed": False, "success": False}

    success = await process_article(article, session, http_client, embed_model, ollama_url)

    return {"aged_out": aged_out, "processed": True, "success": success}
