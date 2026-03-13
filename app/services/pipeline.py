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
from app.services.image_cache import cache_article_image

logger = structlog.get_logger(__name__)


async def process_article(
    candidate: ArticleCandidate,
    session: AsyncSession,
    http_client: RateLimitedClient,
    embed_model: Any,
    similarity_threshold: float | None = None,
    cf_account_id: str | None = None,
    r2_bucket: str | None = None,
    r2_api_token: str | None = None,
    r2_public_url: str | None = None,
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
                # Use extracted og:image as fallback when RSS had no image
                if not article.image_url and extracted.image_url:
                    article.image_url = extracted.image_url
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

        # Step 5: Cache image to R2
        if article.image_url:
            cached_url = await cache_article_image(
                article.image_url, cf_account_id, r2_bucket, r2_api_token, r2_public_url
            )
            if cached_url and cached_url != article.image_url:
                article.image_url = cached_url
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
    cf_account_id: str | None = None,
    r2_bucket: str | None = None,
    r2_api_token: str | None = None,
    r2_public_url: str | None = None,
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
        # Commit in batches of 50 so data is visible incrementally
        batch_size = 50
        for i, candidate in enumerate(candidates):
            try:
                result = await process_article(
                    candidate, session, http_client, embed_model,
                    similarity_threshold=similarity_threshold,
                    cf_account_id=cf_account_id,
                    r2_bucket=r2_bucket,
                    r2_api_token=r2_api_token,
                    r2_public_url=r2_public_url,
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

            if (i + 1) % batch_size == 0:
                await session.commit()
                await log.ainfo(
                    "ingestion_batch_committed",
                    batch=((i + 1) // batch_size),
                    articles_stored=stats["articles_stored"],
                )

        await session.commit()

    except Exception as exc:
        stats["errors"] += 1
        await log.aerror("ingestion_cycle_error", error=str(exc))
        await session.rollback()

    await log.ainfo("ingestion_cycle_complete", **stats)
    return stats
