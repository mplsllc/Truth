"""RSS feed polling orchestrator with per-feed error isolation."""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import mktime
from typing import Optional
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

import feedparser
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.enums import FeedStatus
from app.models.feed import Feed
from app.services.http_client import RateLimitedClient

logger = structlog.get_logger()

# UTM and tracking parameters to strip from URLs
TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_cid", "utm_reader", "utm_name", "utm_social", "utm_social-type",
    "fbclid", "gclid", "gclsrc", "dclid", "msclkid",
})


@dataclass
class ArticleCandidate:
    """Extracted metadata from a single RSS feed entry."""

    title: str
    url: str
    url_hash: str
    summary: Optional[str]
    author: Optional[str]
    published_at: Optional[datetime]
    image_url: Optional[str]
    feed_id: int


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication.

    - Lowercase scheme and host
    - Strip UTM/tracking parameters
    - Remove fragment
    - Remove trailing slash
    """
    parsed = urlparse(url)

    # Lowercase scheme and host
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Strip tracking params
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    filtered_params = {
        k: v for k, v in query_params.items()
        if k.lower() not in TRACKING_PARAMS
    }
    # Rebuild query string sorted for consistency
    query = urlencode(filtered_params, doseq=True) if filtered_params else ""

    # Strip fragment
    fragment = ""

    # Rebuild path, strip trailing slash (but keep root "/")
    path = parsed.path.rstrip("/") if parsed.path != "/" else "/"

    normalized = urlunparse((scheme, netloc, path, parsed.params, query, fragment))
    return normalized


def _extract_image_url(entry) -> Optional[str]:
    """Extract image URL from a feedparser entry, checking multiple fields."""
    # media:content
    if hasattr(entry, "media_content") and entry.media_content:
        for media in entry.media_content:
            if media.get("medium") == "image" or media.get("url", "").endswith(
                (".jpg", ".jpeg", ".png", ".gif", ".webp")
            ):
                return media.get("url")

    # media:thumbnail
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        for thumb in entry.media_thumbnail:
            if thumb.get("url"):
                return thumb["url"]

    # enclosures
    if hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            enc_type = enc.get("type", "")
            if enc_type.startswith("image/") or enc.get("url", "").endswith(
                (".jpg", ".jpeg", ".png", ".gif", ".webp")
            ):
                return enc.get("url")

    # links with image type
    if hasattr(entry, "links"):
        for link in entry.links:
            if link.get("type", "").startswith("image/"):
                return link.get("href")

    return None


def _parse_published(entry) -> Optional[datetime]:
    """Parse the published date from a feedparser entry."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime.fromtimestamp(
                mktime(entry.published_parsed), tz=timezone.utc
            )
        except (ValueError, OverflowError, OSError):
            pass

    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        try:
            return datetime.fromtimestamp(
                mktime(entry.updated_parsed), tz=timezone.utc
            )
        except (ValueError, OverflowError, OSError):
            pass

    return None


async def poll_single_feed(
    feed: Feed,
    session: AsyncSession,
    http_client: RateLimitedClient,
) -> list[ArticleCandidate]:
    """Poll a single RSS feed and return new article candidates.

    Handles errors gracefully: on failure, updates feed health and returns
    an empty list. On success, resets feed health to ACTIVE.

    Args:
        feed: The Feed model to poll.
        session: Async database session.
        http_client: Rate-limited HTTP client.

    Returns:
        List of ArticleCandidate objects for new (non-duplicate) entries.
    """
    log = logger.bind(feed_id=feed.id, feed_name=feed.name, feed_url=feed.url)

    try:
        response = await http_client.get(feed.url)
        feed_data = feedparser.parse(response.text)

        if feed_data.bozo and not feed_data.entries:
            await log.awarn(
                "feed_parse_error",
                bozo_exception=str(feed_data.bozo_exception),
            )
            # Update health to error since we got no entries
            feed.status = FeedStatus.ERROR
            feed.error_count = (feed.error_count or 0) + 1
            feed.last_error = f"Parse error: {feed_data.bozo_exception}"
            await session.flush()
            return []

        if feed_data.bozo:
            await log.awarn(
                "feed_parse_warning",
                bozo_exception=str(feed_data.bozo_exception),
                entry_count=len(feed_data.entries),
            )

        candidates: list[ArticleCandidate] = []

        for entry in feed_data.entries:
            # Extract URL
            url = getattr(entry, "link", None)
            if not url:
                continue

            # Normalize and hash URL
            normalized = normalize_url(url)
            url_hash = hashlib.sha256(normalized.encode()).hexdigest()

            # Check for existing article with same url_hash
            existing = await session.execute(
                select(Article.id).where(Article.url_hash == url_hash)
            )
            if existing.scalar_one_or_none() is not None:
                continue

            # Skip entries older than 7 days to avoid ingesting archives
            published_at = _parse_published(entry)
            if published_at:
                age = datetime.now(timezone.utc) - published_at
                if age > timedelta(days=7):
                    continue

            # Extract metadata
            title = getattr(entry, "title", "Untitled")
            summary_raw = getattr(entry, "summary", None) or getattr(
                entry, "description", None
            )
            summary = re.sub(r"<[^>]+>", "", summary_raw).strip() if summary_raw else None
            author = getattr(entry, "author", None) or entry.get("dc_creator")
            image_url = _extract_image_url(entry)

            candidates.append(
                ArticleCandidate(
                    title=title,
                    url=normalized,
                    url_hash=url_hash,
                    summary=summary,
                    author=author,
                    published_at=published_at,
                    image_url=image_url,
                    feed_id=feed.id,
                )
            )

        # Update feed health: success
        feed.status = FeedStatus.ACTIVE
        feed.error_count = 0
        feed.last_polled_at = datetime.now(timezone.utc)
        feed.last_error = None
        await session.flush()

        await log.ainfo("feed_polled", new_articles=len(candidates))
        return candidates

    except Exception as exc:
        await log.aerror("feed_poll_failed", error=str(exc))
        # Update feed health: error
        feed.status = FeedStatus.ERROR
        feed.error_count = (feed.error_count or 0) + 1
        feed.last_error = str(exc)
        await session.flush()
        return []


async def poll_all_feeds(
    session: AsyncSession,
    http_client: RateLimitedClient,
) -> list[ArticleCandidate]:
    """Poll all active, enabled feeds and return new article candidates.

    Uses asyncio.gather with return_exceptions=True for per-feed error
    isolation. A single broken feed never stops other feeds from polling.

    Args:
        session: Async database session.
        http_client: Rate-limited HTTP client.

    Returns:
        Flat list of all ArticleCandidates from all successful feeds.
    """
    log = logger.bind()

    # Get all enabled, non-disabled feeds
    result = await session.execute(
        select(Feed).where(
            Feed.enabled == True,  # noqa: E712
            Feed.status != FeedStatus.DISABLED,
        )
    )
    feeds = list(result.scalars().all())

    if not feeds:
        await log.ainfo("poll_all_feeds_skip", reason="no active feeds")
        return []

    await log.ainfo("poll_all_feeds_start", feed_count=len(feeds))

    # Poll feeds sequentially -- they share a single async session which
    # does not support concurrent flushes.
    all_candidates: list[ArticleCandidate] = []
    error_count = 0

    for feed in feeds:
        try:
            candidates = await poll_single_feed(feed, session, http_client)
            all_candidates.extend(candidates)
        except Exception as exc:
            error_count += 1
            await log.aerror(
                "feed_poll_error",
                feed_id=feed.id,
                feed_name=feed.name,
                error=str(exc),
            )
            feed.status = FeedStatus.ERROR
            feed.error_count = (feed.error_count or 0) + 1
            feed.last_error = str(exc)

    await session.flush()

    await log.ainfo(
        "poll_all_feeds_complete",
        total_candidates=len(all_candidates),
        feeds_polled=len(feeds),
        feeds_with_errors=error_count,
    )

    return all_candidates
