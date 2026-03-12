"""APScheduler setup with feed polling job."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.db.session import async_session_factory
from app.models.article import Article
from app.services.feed_poller import poll_all_feeds, ArticleCandidate
from app.services.http_client import get_http_client

logger = structlog.get_logger()


async def _run_feed_poll() -> None:
    """Execute a full feed polling cycle.

    Creates a new database session and HTTP client, polls all feeds,
    and saves new articles to the database.
    """
    log = logger.bind()
    settings = get_settings()

    async with async_session_factory() as session:
        client = get_http_client(
            max_concurrent=settings.max_concurrent_requests,
            per_domain_delay=settings.per_domain_delay_seconds,
            proxy=settings.http_proxy,
        )
        async with client:
            try:
                candidates = await poll_all_feeds(session, client)

                # Save new articles to database (without content -- content extraction
                # happens in Plan 03)
                new_count = 0
                for candidate in candidates:
                    article = Article(
                        url=candidate.url,
                        url_hash=candidate.url_hash,
                        title=candidate.title,
                        summary=candidate.summary,
                        author=candidate.author,
                        published_at=candidate.published_at,
                        image_url=candidate.image_url,
                        feed_id=candidate.feed_id,
                    )
                    session.add(article)
                    new_count += 1

                await session.commit()

                await log.ainfo(
                    "feed_poll_cycle_complete",
                    new_articles=new_count,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            except Exception as exc:
                await session.rollback()
                await log.aerror("feed_poll_cycle_error", error=str(exc))
                raise


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the APScheduler instance.

    Returns an AsyncIOScheduler with the feed polling job configured
    to run at the interval specified in settings.

    The scheduler is NOT started -- call scheduler.start() after creation.
    """
    settings = get_settings()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _run_feed_poll,
        trigger="interval",
        minutes=settings.polling_interval_minutes,
        id="feed_poller",
        name="RSS Feed Poller",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),  # Run immediately on start
    )

    return scheduler
