"""APScheduler setup with ingestion pipeline job."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.db.session import async_session_factory
from app.services.http_client import get_http_client
from app.services.pipeline import run_ingestion_cycle

logger = structlog.get_logger()


async def _run_ingestion_pipeline(embed_model=None) -> None:
    """Execute a full ingestion pipeline cycle.

    Creates a fresh database session and HTTP client, runs the full
    pipeline (poll -> extract -> dedup -> cluster -> store), and
    logs cycle statistics.

    Args:
        embed_model: sentence-transformers model from app.state.
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
                stats = await run_ingestion_cycle(
                    session, client, embed_model
                )

                await log.ainfo(
                    "ingestion_pipeline_cycle_complete",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    **stats,
                )

            except Exception as exc:
                await session.rollback()
                await log.aerror("ingestion_pipeline_cycle_error", error=str(exc))
                raise


def create_scheduler(embed_model=None) -> AsyncIOScheduler:
    """Create and configure the APScheduler instance.

    Returns an AsyncIOScheduler with the ingestion pipeline job configured
    to run at the interval specified in settings.

    The scheduler is NOT started -- call scheduler.start() after creation.

    Args:
        embed_model: sentence-transformers model to pass to pipeline jobs.
    """
    settings = get_settings()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _run_ingestion_pipeline,
        trigger="interval",
        minutes=settings.polling_interval_minutes,
        id="ingestion_pipeline",
        name="Ingestion Pipeline",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),  # Run immediately on start
        kwargs={"embed_model": embed_model},
    )

    return scheduler
