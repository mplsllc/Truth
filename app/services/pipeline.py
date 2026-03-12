"""End-to-end ingestion pipeline: poll -> extract -> deduplicate -> cluster -> store.

Orchestrates the full article ingestion cycle, connecting the feed poller,
content extractor, and deduplicator into a single pipeline that runs on
the scheduler.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.enums import FactCheckStatus
from app.config import get_settings
from app.services.content_extractor import extract_content
from app.services.deduplicator import deduplicate_article, find_or_create_cluster
from app.services.feed_poller import ArticleCandidate, poll_all_feeds
from app.services.http_client import RateLimitedClient

logger = structlog.get_logger(__name__)


async def process_article(
    candidate: ArticleCandidate,
    session: AsyncSession,
    http_client: RateLimitedClient,
    embed_model: Any,
    similarity_threshold: float | None = None,
) -> Article | None:
    """Process a single article candidate through the full pipeline.

    Steps:
    1. Create Article record from candidate metadata
    2. Extract full content via content extractor
    3. Deduplicate (URL hash + semantic similarity)
    4. Cluster (create or join StoryCluster)

    Args:
        candidate: ArticleCandidate from feed poller.
        session: Async database session.
        http_client: Rate-limited HTTP client for content extraction.
        embed_model: sentence-transformers model for embeddings.

    Returns:
        The stored Article, or None if it was a duplicate.
    """
    log = logger.bind(url=candidate.url, title=candidate.title)

    try:
        # Step 1: Create Article record from candidate metadata
        article = Article(
            url=candidate.url,
            url_hash=candidate.url_hash,
            title=candidate.title,
            summary=candidate.summary,
            author=candidate.author,
            published_at=candidate.published_at,
            image_url=candidate.image_url,
            feed_id=candidate.feed_id,
            fact_check_status=FactCheckStatus.PENDING,
        )

        # Step 2: Extract full content
        try:
            extracted = await extract_content(candidate.url, http_client)
            if extracted.text:
                article.content = extracted.text
                article.language = extracted.language
                article.is_opinion = extracted.is_opinion
                article.is_wire_story = extracted.is_wire_story
                article.wire_source = extracted.wire_source
            else:
                # Extraction failed -- use RSS summary as content
                article.content = candidate.summary
                await log.awarn(
                    "content_extraction_failed",
                    error=extracted.error,
                    fallback="rss_summary",
                )
        except Exception as exc:
            # Content extraction completely failed -- keep article with RSS data
            article.content = candidate.summary
            await log.awarn(
                "content_extraction_error",
                error=str(exc),
                fallback="rss_summary",
            )

        # Step 3: Deduplicate
        dedup_result = await deduplicate_article(
            article, session, embed_model, similarity_threshold=similarity_threshold
        )

        if dedup_result == "duplicate":
            await log.ainfo("article_duplicate_skipped")
            return None

        # Step 4: Store the article and cluster it
        session.add(article)
        await session.flush()

        cluster_id = dedup_result if isinstance(dedup_result, int) else None
        await find_or_create_cluster(article, cluster_id, session, embed_model)
        await session.flush()

        await log.ainfo(
            "article_processed",
            article_id=article.id,
            cluster_id=article.cluster_id,
        )
        return article

    except Exception as exc:
        await log.aerror("article_processing_error", error=str(exc))
        return None


async def run_ingestion_cycle(
    session: AsyncSession,
    http_client: RateLimitedClient,
    embed_model: Any,
    similarity_threshold: float | None = None,
) -> dict:
    """Run a full ingestion cycle: poll all feeds, process each article.

    Args:
        session: Async database session.
        http_client: Rate-limited HTTP client.
        embed_model: sentence-transformers model.

    Returns:
        Stats dict with counts for feeds_polled, articles_found,
        articles_stored, duplicates_skipped, clusters_created, errors.
    """
    log = logger.bind()
    stats = {
        "feeds_polled": 0,
        "articles_found": 0,
        "articles_stored": 0,
        "duplicates_skipped": 0,
        "errors": 0,
    }

    try:
        # Poll all feeds for candidates
        candidates = await poll_all_feeds(session, http_client)
        stats["articles_found"] = len(candidates)

        await log.ainfo("ingestion_cycle_start", candidates=len(candidates))

        # Process each candidate sequentially (content extraction is rate-limited)
        for candidate in candidates:
            try:
                result = await process_article(
                    candidate, session, http_client, embed_model,
                    similarity_threshold=similarity_threshold,
                )
                if result is not None:
                    stats["articles_stored"] += 1
                else:
                    stats["duplicates_skipped"] += 1
            except Exception as exc:
                stats["errors"] += 1
                await log.aerror(
                    "candidate_processing_error",
                    url=candidate.url,
                    error=str(exc),
                )

        await session.commit()

    except Exception as exc:
        stats["errors"] += 1
        await log.aerror("ingestion_cycle_error", error=str(exc))
        await session.rollback()

    await log.ainfo("ingestion_cycle_complete", **stats)
    return stats
