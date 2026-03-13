"""Tests for database models and seed data."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.article import Article
from app.models.cluster import StoryCluster
from app.models.enums import (
    ClusterStatus,
    FactCheckStatus,
    FeedStatus,
    TrustTier,
)
from app.models.feed import Feed

SEED_FILE = Path(__file__).parent.parent / "seed" / "feeds.json"


class TestEnums:
    """Test enum values are correctly defined."""

    def test_trust_tier_values(self):
        assert TrustTier.HIGH.value == "high"
        assert TrustTier.MEDIUM.value == "medium"
        assert TrustTier.LOW.value == "low"
        assert len(TrustTier) == 3

    def test_feed_status_values(self):
        assert FeedStatus.ACTIVE.value == "active"
        assert FeedStatus.DISABLED.value == "disabled"
        assert FeedStatus.ERROR.value == "error"
        assert len(FeedStatus) == 3

    def test_cluster_status_values(self):
        assert ClusterStatus.ACTIVE.value == "active"
        assert ClusterStatus.CLOSED.value == "closed"
        assert len(ClusterStatus) == 2

    def test_fact_check_status_values(self):
        assert FactCheckStatus.PENDING.value == "pending"
        assert FactCheckStatus.IN_PROGRESS.value == "in_progress"
        assert FactCheckStatus.COMPLETE.value == "complete"
        assert FactCheckStatus.FAILED.value == "failed"
        assert FactCheckStatus.EXPIRED.value == "expired"
        assert len(FactCheckStatus) == 5


class TestFeedModel:
    """Test Feed model creation and fields."""

    @pytest.mark.asyncio
    async def test_create_feed(self, db_session):
        feed = Feed(
            name="Test Feed",
            url="https://example.com/rss",
            website_url="https://example.com",
            trust_tier=TrustTier.HIGH,
            category="general",
            region="us",
        )
        db_session.add(feed)
        await db_session.flush()

        assert feed.id is not None
        assert feed.name == "Test Feed"
        assert feed.url == "https://example.com/rss"
        assert feed.trust_tier == TrustTier.HIGH
        assert feed.enabled is True
        assert feed.error_count == 0
        assert feed.article_count == 0
        assert feed.status == FeedStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_feed_unique_url(self, db_session):
        feed1 = Feed(name="Feed 1", url="https://example.com/rss")
        feed2 = Feed(name="Feed 2", url="https://example.com/rss")
        db_session.add(feed1)
        await db_session.flush()
        db_session.add(feed2)
        with pytest.raises(Exception):
            await db_session.flush()


class TestArticleModel:
    """Test Article model creation and relationships."""

    @pytest.mark.asyncio
    async def test_create_article_with_feed(self, db_session):
        feed = Feed(name="Test Feed", url="https://example.com/rss")
        db_session.add(feed)
        await db_session.flush()

        article = Article(
            url="https://example.com/article/1",
            url_hash="abc123def456",
            title="Test Article Title",
            content="This is the full article content.",
            summary="Short summary of the article.",
            author="Jane Doe",
            feed_id=feed.id,
        )
        db_session.add(article)
        await db_session.flush()

        assert article.id is not None
        assert article.feed_id == feed.id
        assert article.is_opinion is False
        assert article.is_wire_story is False
        assert article.wire_source is None
        assert article.fact_check_status == FactCheckStatus.PENDING
        assert article.cluster_id is None

    @pytest.mark.asyncio
    async def test_article_with_cluster(self, db_session):
        feed = Feed(name="Test Feed", url="https://example2.com/rss")
        db_session.add(feed)
        await db_session.flush()

        cluster = StoryCluster(title="Test Cluster", status=ClusterStatus.ACTIVE)
        db_session.add(cluster)
        await db_session.flush()

        article = Article(
            url="https://example.com/article/2",
            url_hash="xyz789uvw012",
            title="Clustered Article",
            feed_id=feed.id,
            cluster_id=cluster.id,
        )
        db_session.add(article)
        await db_session.flush()

        assert article.cluster_id == cluster.id


class TestStoryClusterModel:
    """Test StoryCluster model creation."""

    @pytest.mark.asyncio
    async def test_create_cluster(self, db_session):
        cluster = StoryCluster(
            title="Breaking News Story",
            summary="Multiple sources report on this event.",
            status=ClusterStatus.ACTIVE,
            article_count=3,
            category="politics",
        )
        db_session.add(cluster)
        await db_session.flush()

        assert cluster.id is not None
        assert cluster.title == "Breaking News Story"
        assert cluster.status == ClusterStatus.ACTIVE
        assert cluster.article_count == 3
        assert cluster.embedding is None
        assert cluster.composite_score is None

    @pytest.mark.asyncio
    async def test_cluster_defaults(self, db_session):
        cluster = StoryCluster()
        db_session.add(cluster)
        await db_session.flush()

        assert cluster.status == ClusterStatus.ACTIVE
        assert cluster.article_count == 1


class TestSeedFeeds:
    """Test seed/feeds.json validity."""

    def test_seed_file_exists(self):
        assert SEED_FILE.exists(), f"Seed file not found at {SEED_FILE}"

    def test_seed_file_is_valid_json(self):
        with open(SEED_FILE) as f:
            data = json.load(f)
        assert isinstance(data, list)

    def test_seed_file_has_50_plus_entries(self):
        with open(SEED_FILE) as f:
            data = json.load(f)
        assert len(data) >= 50, f"Only {len(data)} feeds, need at least 50"

    def test_seed_entries_have_required_fields(self):
        required_fields = {"name", "url", "trust_tier", "category", "region"}
        with open(SEED_FILE) as f:
            data = json.load(f)
        for i, entry in enumerate(data):
            missing = required_fields - set(entry.keys())
            assert not missing, f"Feed {i} ({entry.get('name', '?')}) missing: {missing}"

    def test_seed_trust_tiers_are_valid(self):
        valid_tiers = {"high", "medium", "low"}
        with open(SEED_FILE) as f:
            data = json.load(f)
        for entry in data:
            assert entry["trust_tier"] in valid_tiers, (
                f"{entry['name']} has invalid trust_tier: {entry['trust_tier']}"
            )

    def test_seed_has_all_trust_tiers(self):
        with open(SEED_FILE) as f:
            data = json.load(f)
        tiers = {entry["trust_tier"] for entry in data}
        assert "high" in tiers, "No HIGH trust feeds"
        assert "medium" in tiers, "No MEDIUM trust feeds"
        assert "low" in tiers, "No LOW trust feeds"

    def test_seed_urls_are_valid(self):
        with open(SEED_FILE) as f:
            data = json.load(f)
        for entry in data:
            assert entry["url"].startswith("http"), (
                f"{entry['name']} has invalid URL: {entry['url']}"
            )
