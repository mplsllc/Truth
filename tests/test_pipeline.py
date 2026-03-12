"""Tests for the end-to-end ingestion pipeline."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.models.article import Article
from app.models.cluster import StoryCluster
from app.models.enums import FeedStatus, TrustTier
from app.models.feed import Feed
from app.services.content_extractor import ExtractedContent
from app.services.feed_poller import ArticleCandidate, normalize_url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_pipeline_feed_counter = 2000
_pipeline_article_counter = 8000


def make_feed(db_session, feed_id=None, trust_tier=TrustTier.MEDIUM) -> Feed:
    """Create and add a Feed to the session."""
    global _pipeline_feed_counter
    _pipeline_feed_counter += 1
    if feed_id is None:
        feed_id = _pipeline_feed_counter
    feed = Feed(
        id=feed_id,
        name=f"Test Feed {feed_id}",
        url=f"https://pipeline-feed{feed_id}.example.com/rss",
        trust_tier=trust_tier,
    )
    db_session.add(feed)
    return feed


def make_candidate(
    feed_id: int = 1,
    url: str | None = None,
    title: str = "Test Article Title",
    summary: str = "Test article summary for testing purposes",
) -> ArticleCandidate:
    """Create an ArticleCandidate."""
    global _pipeline_article_counter
    if url is None:
        _pipeline_article_counter += 1
        url = f"https://pipeline-test.example.com/article-{_pipeline_article_counter}"
    normalized = normalize_url(url)
    url_hash = hashlib.sha256(normalized.encode()).hexdigest()
    return ArticleCandidate(
        title=title,
        url=normalized,
        url_hash=url_hash,
        summary=summary,
        author="Test Author",
        published_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        image_url="https://example.com/image.jpg",
        feed_id=feed_id,
    )


def make_mock_embed_model():
    """Create a mock embedding model returning deterministic vectors."""
    mock = MagicMock()
    mock.encode.return_value = [1.0] + [0.0] * 383
    return mock


def make_mock_http_client():
    """Create a mock RateLimitedClient."""
    from app.services.http_client import RateLimitedClient

    mock = AsyncMock(spec=RateLimitedClient)
    return mock


def make_extracted_content(
    text: str = "Full article content " * 20,
    is_opinion: bool = False,
    is_wire_story: bool = False,
    wire_source: str | None = None,
    error: str | None = None,
) -> ExtractedContent:
    """Create an ExtractedContent result."""
    return ExtractedContent(
        text=text,
        title="Extracted Title",
        author="Extracted Author",
        language="en",
        is_opinion=is_opinion,
        is_wire_story=is_wire_story,
        wire_source=wire_source,
        error=error,
    )


# ---------------------------------------------------------------------------
# Test: process_article
# ---------------------------------------------------------------------------


class TestProcessArticle:
    """Tests for process_article function."""

    @pytest.mark.asyncio
    async def test_new_article_creates_article_and_cluster(self, db_session):
        """process_article with new unique article creates Article + StoryCluster."""
        from app.services.pipeline import process_article

        feed = make_feed(db_session)
        await db_session.flush()

        candidate = make_candidate(feed_id=feed.id)
        mock_model = make_mock_embed_model()
        mock_client = make_mock_http_client()

        with patch(
            "app.services.pipeline.extract_content",
            return_value=make_extracted_content(),
        ):
            result = await process_article(
                candidate, db_session, mock_client, mock_model,
                similarity_threshold=0.83,
            )

        assert result is not None
        assert isinstance(result, Article)
        assert result.title == "Test Article Title"
        assert result.content is not None
        assert result.cluster_id is not None

        # Verify cluster was created
        cluster = await db_session.get(StoryCluster, result.cluster_id)
        assert cluster is not None
        assert cluster.primary_article_id == result.id
        assert cluster.article_count == 1

    @pytest.mark.asyncio
    async def test_duplicate_url_returns_none(self, db_session):
        """process_article with duplicate URL returns None."""
        from app.services.pipeline import process_article

        feed = make_feed(db_session)
        await db_session.flush()

        # Insert existing article with same URL
        url = "https://example.com/existing-article"
        normalized = normalize_url(url)
        url_hash = hashlib.sha256(normalized.encode()).hexdigest()
        existing = Article(
            url=normalized,
            url_hash=url_hash,
            title="Existing Article",
            feed_id=feed.id,
        )
        db_session.add(existing)
        await db_session.flush()

        candidate = make_candidate(
            feed_id=feed.id,
            url=url,
            title="Same URL Different Title",
        )
        mock_model = make_mock_embed_model()
        mock_client = make_mock_http_client()

        with patch(
            "app.services.pipeline.extract_content",
            return_value=make_extracted_content(),
        ):
            result = await process_article(
                candidate, db_session, mock_client, mock_model,
                similarity_threshold=0.83,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_extraction_failure_saves_with_rss_summary(self, db_session):
        """process_article with content extraction failure still saves article with RSS summary."""
        from app.services.pipeline import process_article

        feed = make_feed(db_session)
        await db_session.flush()

        summary = "This is the RSS summary fallback content"
        candidate = make_candidate(
            feed_id=feed.id,
            url="https://example.com/extraction-fails",
            summary=summary,
        )
        mock_model = make_mock_embed_model()
        mock_client = make_mock_http_client()

        # Extraction returns error
        with patch(
            "app.services.pipeline.extract_content",
            return_value=ExtractedContent(error="extraction_failed"),
        ):
            result = await process_article(
                candidate, db_session, mock_client, mock_model,
                similarity_threshold=0.83,
            )

        assert result is not None
        assert result.content == summary  # Falls back to RSS summary
        assert result.cluster_id is not None

    @pytest.mark.asyncio
    async def test_extraction_exception_saves_with_rss_summary(self, db_session):
        """process_article when extract_content raises exception still saves with RSS summary."""
        from app.services.pipeline import process_article

        feed = make_feed(db_session)
        await db_session.flush()

        summary = "RSS summary used as fallback"
        candidate = make_candidate(
            feed_id=feed.id,
            url="https://example.com/extraction-crashes",
            summary=summary,
        )
        mock_model = make_mock_embed_model()
        mock_client = make_mock_http_client()

        with patch(
            "app.services.pipeline.extract_content",
            side_effect=Exception("Network error"),
        ):
            result = await process_article(
                candidate, db_session, mock_client, mock_model,
                similarity_threshold=0.83,
            )

        assert result is not None
        assert result.content == summary


# ---------------------------------------------------------------------------
# Test: run_ingestion_cycle
# ---------------------------------------------------------------------------


class TestRunIngestionCycle:
    """Tests for run_ingestion_cycle function."""

    @pytest.mark.asyncio
    async def test_returns_correct_stats_dict(self, db_session):
        """run_ingestion_cycle returns correct stats dict with all expected keys."""
        from app.services.pipeline import run_ingestion_cycle

        feed = make_feed(db_session)
        await db_session.flush()

        mock_model = make_mock_embed_model()
        mock_client = make_mock_http_client()

        candidates = [
            make_candidate(
                feed_id=feed.id,
                url=f"https://example.com/article-{i}",
                title=f"Article {i}",
            )
            for i in range(3)
        ]

        # Patch session.commit to be a no-op (avoid actual commits in test)
        original_commit = db_session.commit
        db_session.commit = AsyncMock()

        with patch(
            "app.services.pipeline.poll_all_feeds",
            return_value=candidates,
        ), patch(
            "app.services.pipeline.extract_content",
            return_value=make_extracted_content(),
        ):
            stats = await run_ingestion_cycle(db_session, mock_client, mock_model, similarity_threshold=0.83)

        db_session.commit = original_commit

        assert isinstance(stats, dict)
        assert "articles_found" in stats
        assert "articles_stored" in stats
        assert "duplicates_skipped" in stats
        assert "errors" in stats
        assert stats["articles_found"] == 3
        assert stats["articles_stored"] == 3
        assert stats["duplicates_skipped"] == 0
        assert stats["errors"] == 0

    @pytest.mark.asyncio
    async def test_handles_empty_poll_results(self, db_session):
        """run_ingestion_cycle with no candidates returns zero stats."""
        from app.services.pipeline import run_ingestion_cycle

        mock_model = make_mock_embed_model()
        mock_client = make_mock_http_client()

        original_commit = db_session.commit
        db_session.commit = AsyncMock()

        with patch(
            "app.services.pipeline.poll_all_feeds",
            return_value=[],
        ):
            stats = await run_ingestion_cycle(db_session, mock_client, mock_model, similarity_threshold=0.83)

        db_session.commit = original_commit

        assert stats["articles_found"] == 0
        assert stats["articles_stored"] == 0

    @pytest.mark.asyncio
    async def test_counts_duplicates_correctly(self, db_session):
        """run_ingestion_cycle counts duplicates correctly when articles already exist."""
        from app.services.pipeline import run_ingestion_cycle

        feed = make_feed(db_session)
        await db_session.flush()

        # Pre-insert an article
        url = "https://example.com/already-exists"
        normalized = normalize_url(url)
        url_hash = hashlib.sha256(normalized.encode()).hexdigest()
        existing = Article(
            url=normalized,
            url_hash=url_hash,
            title="Already Exists",
            feed_id=feed.id,
        )
        db_session.add(existing)
        await db_session.flush()

        candidates = [
            make_candidate(
                feed_id=feed.id,
                url=url,  # duplicate
                title="Duplicate Article",
            ),
            make_candidate(
                feed_id=feed.id,
                url="https://example.com/brand-new-article",
                title="New Article",
            ),
        ]

        mock_model = make_mock_embed_model()
        mock_client = make_mock_http_client()

        # Patch session.commit to be a no-op (avoid actual commits in test)
        original_commit = db_session.commit
        db_session.commit = AsyncMock()

        with patch(
            "app.services.pipeline.poll_all_feeds",
            return_value=candidates,
        ), patch(
            "app.services.pipeline.extract_content",
            return_value=make_extracted_content(),
        ):
            stats = await run_ingestion_cycle(db_session, mock_client, mock_model, similarity_threshold=0.83)

        db_session.commit = original_commit

        assert stats["articles_found"] == 2
        assert stats["articles_stored"] == 1
        assert stats["duplicates_skipped"] == 1
