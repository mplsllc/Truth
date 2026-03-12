"""Truth news aggregator -- FastAPI application entry point."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func

from app.config import get_settings
from app.db.session import async_session_factory
from app.models.article import Article
from app.models.feed import Feed
from app.models.enums import TrustTier, FeedStatus
from app.tasks.scheduler import create_scheduler

SEED_FILE = Path(__file__).parent.parent / "seed" / "feeds.json"

settings = get_settings()


def configure_logging() -> None:
    """Configure structlog for JSON output."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


async def load_seed_feeds() -> None:
    """Load seed feeds into the database if the feeds table is empty."""
    log = structlog.get_logger()

    async with async_session_factory() as session:
        count = await session.scalar(select(func.count(Feed.id)))
        if count and count > 0:
            await log.ainfo("seed_feeds_skip", reason="feeds already exist", count=count)
            return

        if not SEED_FILE.exists():
            await log.awarn("seed_feeds_missing", path=str(SEED_FILE))
            return

        with open(SEED_FILE) as f:
            feeds_data = json.load(f)

        for entry in feeds_data:
            feed = Feed(
                name=entry["name"],
                url=entry["url"],
                website_url=entry.get("website_url"),
                trust_tier=TrustTier(entry.get("trust_tier", "medium")),
                category=entry.get("category"),
                region=entry.get("region"),
                status=FeedStatus.ACTIVE,
                enabled=True,
            )
            session.add(feed)

        await session.commit()
        await log.ainfo("seed_feeds_loaded", count=len(feeds_data))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown tasks."""
    configure_logging()
    log = structlog.get_logger()
    await log.ainfo("app_starting", version="0.1.0")

    # Load seed feeds on first run
    try:
        await load_seed_feeds()
    except Exception as exc:
        await log.awarn("seed_feeds_error", error=str(exc))

    # Store session factory on app state for dependency injection
    app.state.async_session_factory = async_session_factory

    # Load sentence-transformers embedding model (once at startup per Pitfall 2)
    try:
        from sentence_transformers import SentenceTransformer

        embed_model = SentenceTransformer("all-MiniLM-L6-v2")
        app.state.embed_model = embed_model
        await log.ainfo("embed_model_loaded", model="all-MiniLM-L6-v2")
    except Exception as exc:
        app.state.embed_model = None
        await log.awarn("embed_model_load_failed", error=str(exc))

    # Create and start the APScheduler
    try:
        scheduler = create_scheduler()
        scheduler.start()
        app.state.scheduler = scheduler
        await log.ainfo("scheduler_started")
    except Exception as exc:
        app.state.scheduler = None
        await log.awarn("scheduler_start_failed", error=str(exc))

    yield

    # Shutdown scheduler
    if getattr(app.state, "scheduler", None):
        app.state.scheduler.shutdown(wait=False)
        await log.ainfo("scheduler_stopped")

    await log.ainfo("app_shutting_down")


app = FastAPI(
    title="Truth",
    description="A fact-checked news aggregator powered by local LLM",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/status")
async def system_status():
    """System status endpoint showing feeds, articles, scheduler state, and last poll time."""
    async with async_session_factory() as session:
        feed_count = await session.scalar(select(func.count(Feed.id))) or 0
        article_count = await session.scalar(select(func.count(Article.id))) or 0

        # Get last poll time from most recently polled feed
        last_poll_result = await session.scalar(
            select(func.max(Feed.last_polled_at))
        )

    scheduler = getattr(app.state, "scheduler", None)
    scheduler_running = scheduler is not None and scheduler.running if scheduler else False

    return {
        "feeds": feed_count,
        "articles": article_count,
        "scheduler_running": scheduler_running,
        "last_poll_time": last_poll_result.isoformat() if last_poll_result else None,
        "version": "0.1.0",
    }
