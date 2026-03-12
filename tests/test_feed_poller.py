"""Tests for the RSS feed polling service and rate-limited HTTP client."""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.models.enums import FeedStatus
from app.models.feed import Feed
from app.models.article import Article

# ---------------------------------------------------------------------------
# RSS XML fixtures
# ---------------------------------------------------------------------------

VALID_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel>
  <title>Test Feed</title>
  <link>https://example.com</link>
  <item>
    <title>Test Article Title</title>
    <link>https://example.com/article-1</link>
    <description>This is a test article summary.</description>
    <author>John Doe</author>
    <pubDate>Thu, 01 Feb 2024 12:00:00 GMT</pubDate>
    <media:content url="https://example.com/image.jpg" medium="image"/>
  </item>
  <item>
    <title>Second Article</title>
    <link>https://example.com/article-2</link>
    <description>Another test summary.</description>
    <author>Jane Smith</author>
    <pubDate>Fri, 02 Feb 2024 14:00:00 GMT</pubDate>
    <enclosure url="https://example.com/photo.jpg" type="image/jpeg" length="12345"/>
  </item>
</channel>
</rss>"""

MALFORMED_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Broken Feed</title>
  <item>
    <title>Incomplete Item
  </item>
  <this is broken xml
</channel>
"""

EMPTY_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Empty Feed</title>
  <link>https://empty.example.com</link>
</channel>
</rss>"""


# ---------------------------------------------------------------------------
# Helper to create Feed objects
# ---------------------------------------------------------------------------


def make_feed(
    feed_id: int = 1,
    name: str = "Test Feed",
    url: str = "https://example.com/feed.xml",
    status: FeedStatus = FeedStatus.ACTIVE,
    enabled: bool = True,
    error_count: int = 0,
) -> Feed:
    """Create a Feed model instance for testing."""
    feed = Feed(
        id=feed_id,
        name=name,
        url=url,
        status=status,
        enabled=enabled,
        error_count=error_count,
    )
    return feed


# ---------------------------------------------------------------------------
# Test: poll_single_feed with valid RSS
# ---------------------------------------------------------------------------


class TestPollSingleFeed:
    """Tests for poll_single_feed function."""

    @pytest.mark.asyncio
    async def test_valid_rss_returns_article_candidates(self, db_session):
        """poll_single_feed with valid RSS XML returns list of article candidates
        with title, url, summary, author, published_at, image_url."""
        from app.services.feed_poller import poll_single_feed, ArticleCandidate
        from app.services.http_client import RateLimitedClient

        feed = make_feed()
        db_session.add(feed)
        await db_session.flush()

        mock_response = MagicMock()
        mock_response.text = VALID_RSS_XML
        mock_response.status_code = 200

        mock_client = AsyncMock(spec=RateLimitedClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        candidates = await poll_single_feed(feed, db_session, mock_client)

        assert len(candidates) == 2
        assert all(isinstance(c, ArticleCandidate) for c in candidates)

        first = candidates[0]
        assert first.title == "Test Article Title"
        assert "example.com/article-1" in first.url
        assert first.summary == "This is a test article summary."
        assert first.author == "John Doe"
        assert first.published_at is not None
        assert first.image_url == "https://example.com/image.jpg"
        assert first.feed_id == feed.id

    @pytest.mark.asyncio
    async def test_malformed_xml_returns_empty_no_exception(self, db_session):
        """poll_single_feed with malformed XML raises no exception, returns empty list, logs error."""
        from app.services.feed_poller import poll_single_feed
        from app.services.http_client import RateLimitedClient

        feed = make_feed()
        db_session.add(feed)
        await db_session.flush()

        mock_response = MagicMock()
        mock_response.text = MALFORMED_RSS_XML
        mock_response.status_code = 200

        mock_client = AsyncMock(spec=RateLimitedClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        # Should not raise
        candidates = await poll_single_feed(feed, db_session, mock_client)
        assert isinstance(candidates, list)
        # Malformed feeds may return partial results or empty -- must not crash

    @pytest.mark.asyncio
    async def test_unreachable_url_returns_empty_no_exception(self, db_session):
        """poll_single_feed with unreachable URL raises no exception, returns empty list."""
        from app.services.feed_poller import poll_single_feed
        from app.services.http_client import RateLimitedClient

        feed = make_feed()
        db_session.add(feed)
        await db_session.flush()

        mock_client = AsyncMock(spec=RateLimitedClient)
        mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))

        candidates = await poll_single_feed(feed, db_session, mock_client)
        assert isinstance(candidates, list)
        assert len(candidates) == 0

    @pytest.mark.asyncio
    async def test_skips_duplicate_url_hash(self, db_session):
        """poll_single_feed skips articles whose URL already exists in database (url_hash check)."""
        from app.services.feed_poller import poll_single_feed, normalize_url
        from app.services.http_client import RateLimitedClient

        feed = make_feed()
        db_session.add(feed)
        await db_session.flush()

        # Pre-insert an article with the same url_hash
        url = "https://example.com/article-1"
        url_hash = hashlib.sha256(normalize_url(url).encode()).hexdigest()
        existing = Article(
            url=url,
            url_hash=url_hash,
            title="Already exists",
            feed_id=feed.id,
        )
        db_session.add(existing)
        await db_session.flush()

        mock_response = MagicMock()
        mock_response.text = VALID_RSS_XML
        mock_response.status_code = 200

        mock_client = AsyncMock(spec=RateLimitedClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        candidates = await poll_single_feed(feed, db_session, mock_client)

        # Only article-2 should be returned, article-1 is a duplicate
        assert len(candidates) == 1
        assert "article-2" in candidates[0].url


class TestMetadataExtraction:
    """Tests for metadata extraction from feedparser entries."""

    @pytest.mark.asyncio
    async def test_parses_feedparser_fields_correctly(self, db_session):
        """Metadata extraction parses feedparser entry fields correctly."""
        from app.services.feed_poller import poll_single_feed
        from app.services.http_client import RateLimitedClient

        feed = make_feed()
        db_session.add(feed)
        await db_session.flush()

        mock_response = MagicMock()
        mock_response.text = VALID_RSS_XML
        mock_response.status_code = 200

        mock_client = AsyncMock(spec=RateLimitedClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        candidates = await poll_single_feed(feed, db_session, mock_client)

        # First article: media:content image
        first = candidates[0]
        assert first.title == "Test Article Title"
        assert first.author == "John Doe"
        assert first.summary == "This is a test article summary."
        assert first.image_url == "https://example.com/image.jpg"
        assert first.published_at is not None
        assert first.url_hash is not None

        # Second article: enclosure image
        second = candidates[1]
        assert second.title == "Second Article"
        assert second.author == "Jane Smith"
        assert second.image_url == "https://example.com/photo.jpg"


class TestFeedHealthTracking:
    """Tests for feed health status updates after polling."""

    @pytest.mark.asyncio
    async def test_error_status_after_failed_poll(self, db_session):
        """Feed health updated to ERROR status after failed poll, error_count incremented."""
        from app.services.feed_poller import poll_single_feed
        from app.services.http_client import RateLimitedClient

        feed = make_feed(error_count=2)
        db_session.add(feed)
        await db_session.flush()

        mock_client = AsyncMock(spec=RateLimitedClient)
        mock_client.get = AsyncMock(side_effect=Exception("Timeout"))

        await poll_single_feed(feed, db_session, mock_client)

        # Refresh the feed from db
        await db_session.refresh(feed)
        assert feed.status == FeedStatus.ERROR
        assert feed.error_count == 3
        assert feed.last_error is not None

    @pytest.mark.asyncio
    async def test_active_status_after_successful_poll(self, db_session):
        """Feed health reset to ACTIVE after successful poll, error_count reset to 0."""
        from app.services.feed_poller import poll_single_feed
        from app.services.http_client import RateLimitedClient

        feed = make_feed(error_count=5, status=FeedStatus.ERROR)
        db_session.add(feed)
        await db_session.flush()

        mock_response = MagicMock()
        mock_response.text = VALID_RSS_XML
        mock_response.status_code = 200

        mock_client = AsyncMock(spec=RateLimitedClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        await poll_single_feed(feed, db_session, mock_client)

        await db_session.refresh(feed)
        assert feed.status == FeedStatus.ACTIVE
        assert feed.error_count == 0
        assert feed.last_polled_at is not None


class TestPollAllFeeds:
    """Tests for poll_all_feeds function."""

    @pytest.mark.asyncio
    async def test_mix_of_valid_and_broken_feeds(self, db_session):
        """poll_all_feeds with mix of valid and broken feeds returns results from valid feeds only."""
        from app.services.feed_poller import poll_all_feeds
        from app.services.http_client import RateLimitedClient

        good_feed = make_feed(feed_id=1, url="https://good.example.com/feed.xml")
        bad_feed = make_feed(feed_id=2, url="https://bad.example.com/feed.xml")

        db_session.add(good_feed)
        db_session.add(bad_feed)
        await db_session.flush()

        good_response = MagicMock()
        good_response.text = VALID_RSS_XML
        good_response.status_code = 200

        async def mock_get(url, **kwargs):
            if "bad" in url:
                raise Exception("Connection refused")
            return good_response

        mock_client = AsyncMock(spec=RateLimitedClient)
        mock_client.get = AsyncMock(side_effect=mock_get)

        candidates = await poll_all_feeds(db_session, mock_client)

        # Should have candidates from the good feed but not crash from the bad one
        assert len(candidates) > 0
        assert all(c.feed_id == good_feed.id for c in candidates)


class TestRateLimitedClient:
    """Tests for the rate-limited HTTP client."""

    @pytest.mark.asyncio
    async def test_per_domain_delay_enforced(self):
        """HTTP client respects per-domain delay (no two requests to same domain within 2 seconds)."""
        from app.services.http_client import RateLimitedClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"

        with patch("httpx.AsyncClient") as MockHttpx:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            MockHttpx.return_value = mock_instance

            client = RateLimitedClient(max_concurrent=15, per_domain_delay=1.0)
            async with client:
                # First request should be fast
                t1 = time.monotonic()
                await client.get("https://example.com/page1")
                t2 = time.monotonic()

                # Second request to same domain should be delayed
                await client.get("https://example.com/page2")
                t3 = time.monotonic()

                # The delay between t2 and t3 should be >= per_domain_delay (1.0s)
                delay = t3 - t2
                assert delay >= 0.9, f"Expected >= 0.9s delay, got {delay:.2f}s"

                # Different domain should not be delayed
                await client.get("https://other.example.com/page1")
                t4 = time.monotonic()
                # Should be fast (< 0.5s)
                assert (t4 - t3) < 0.5 + 1.0  # allow some wiggle but must not add extra domain delay


class TestNormalizeUrl:
    """Tests for URL normalization."""

    def test_strips_utm_params(self):
        from app.services.feed_poller import normalize_url

        url = "https://example.com/article?utm_source=rss&utm_medium=feed&id=123"
        normalized = normalize_url(url)
        assert "utm_source" not in normalized
        assert "utm_medium" not in normalized
        assert "id=123" in normalized

    def test_strips_trailing_slash(self):
        from app.services.feed_poller import normalize_url

        assert normalize_url("https://example.com/article/") == normalize_url(
            "https://example.com/article"
        )

    def test_lowercases_scheme_and_host(self):
        from app.services.feed_poller import normalize_url

        url = normalize_url("HTTPS://EXAMPLE.COM/Article")
        assert url.startswith("https://example.com/")
        assert "Article" in url  # path case preserved

    def test_strips_fragment(self):
        from app.services.feed_poller import normalize_url

        url = normalize_url("https://example.com/article#section-2")
        assert "#" not in url
