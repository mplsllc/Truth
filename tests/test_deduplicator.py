"""Tests for the two-phase deduplication service (URL hash + semantic similarity)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.models.article import Article
from app.models.cluster import StoryCluster
from app.models.enums import ClusterStatus, TrustTier
from app.models.feed import Feed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_dedup_feed_counter = 1000
_dedup_article_counter = 5000


def make_feed(
    db_session,
    feed_id: int | None = None,
    name: str = "Test Feed",
    url: str | None = None,
    trust_tier: TrustTier = TrustTier.MEDIUM,
) -> Feed:
    """Create and add a Feed to the session."""
    global _dedup_feed_counter
    _dedup_feed_counter += 1
    if feed_id is None:
        feed_id = _dedup_feed_counter
    if url is None:
        url = f"https://dedup-test-{feed_id}.example.com/feed.xml"
    feed = Feed(id=feed_id, name=name, url=url, trust_tier=trust_tier)
    db_session.add(feed)
    return feed


def make_article(
    db_session,
    feed_id: int,
    url: str | None = None,
    title: str = "Test Article",
    summary: str | None = "Test summary content here for embedding purposes",
    is_opinion: bool = False,
    cluster_id: int | None = None,
) -> Article:
    """Create and add an Article to the session."""
    global _dedup_article_counter
    from app.services.feed_poller import normalize_url

    if url is None:
        _dedup_article_counter += 1
        url = f"https://dedup-test.example.com/article-{_dedup_article_counter}"
    normalized = normalize_url(url)
    url_hash = hashlib.sha256(normalized.encode()).hexdigest()
    article = Article(
        url=normalized,
        url_hash=url_hash,
        title=title,
        summary=summary,
        feed_id=feed_id,
        is_opinion=is_opinion,
        cluster_id=cluster_id,
    )
    db_session.add(article)
    return article


def make_mock_embed_model(vector: list[float] | None = None):
    """Create a mock sentence-transformers model that returns deterministic vectors.

    Default returns a unit vector in first dimension [1, 0, 0, ...] (384 dims).
    """
    mock_model = MagicMock()
    if vector is None:
        vector = [1.0] + [0.0] * 383
    mock_model.encode.return_value = vector
    return mock_model


def make_similar_vector() -> list[float]:
    """Return a vector very similar to default (cosine sim > 0.83)."""
    # Slightly perturbed version of [1, 0, 0, ...]: cosine sim ~ 0.99
    vec = [0.99] + [0.1] + [0.0] * 382
    return vec


def make_dissimilar_vector() -> list[float]:
    """Return a vector orthogonal to default (cosine sim ~ 0)."""
    return [0.0, 1.0] + [0.0] * 382


def make_moderate_vector() -> list[float]:
    """Return a vector with moderate similarity (cosine sim ~ 0.70, below threshold)."""
    vec = [0.7, 0.7] + [0.0] * 382
    return vec


# ---------------------------------------------------------------------------
# Test: deduplicate_article
# ---------------------------------------------------------------------------


class TestDeduplicateArticle:
    """Tests for deduplicate_article function."""

    @pytest.mark.asyncio
    async def test_new_unique_url_returns_new(self, db_session):
        """deduplicate_article with new unique URL returns 'new' (no existing match)."""
        from app.services.deduplicator import deduplicate_article

        feed = make_feed(db_session)
        await db_session.flush()

        article = make_article(db_session, feed_id=feed.id)
        await db_session.flush()

        mock_model = make_mock_embed_model()

        result = await deduplicate_article(article, db_session, mock_model, similarity_threshold=0.83)

        assert result == "new"

    @pytest.mark.asyncio
    async def test_existing_url_hash_returns_duplicate(self, db_session):
        """deduplicate_article with existing url_hash returns 'duplicate' (exact URL match)."""
        from app.services.deduplicator import deduplicate_article
        from app.services.feed_poller import normalize_url

        feed = make_feed(db_session)
        await db_session.flush()

        # Insert an existing article
        existing = make_article(
            db_session,
            feed_id=feed.id,
            url="https://example.com/same-article",
            title="Existing Article",
        )
        await db_session.flush()

        # Create an Article object with the same URL but don't add to session
        # (simulates what pipeline would do before dedup check)
        url = "https://example.com/same-article"
        normalized = normalize_url(url)
        url_hash = hashlib.sha256(normalized.encode()).hexdigest()
        new_article = Article(
            url=normalized,
            url_hash=url_hash,
            title="Same URL Different Title",
            feed_id=feed.id,
        )

        mock_model = make_mock_embed_model()

        result = await deduplicate_article(new_article, db_session, mock_model, similarity_threshold=0.83)

        assert result == "duplicate"

    @pytest.mark.asyncio
    async def test_semantically_similar_returns_cluster_id(self, db_session):
        """deduplicate_article with semantically similar title+summary returns cluster_id."""
        from app.services.deduplicator import deduplicate_article, find_or_create_cluster

        feed = make_feed(db_session)
        await db_session.flush()

        # Create first article and cluster it
        first_article = make_article(
            db_session,
            feed_id=feed.id,
            url="https://source1.com/article-about-event",
            title="Major Event Happens Today",
        )
        await db_session.flush()

        mock_model_first = make_mock_embed_model([1.0] + [0.0] * 383)
        cluster = await find_or_create_cluster(
            first_article, None, db_session, mock_model_first
        )
        await db_session.flush()

        # Now try to deduplicate a semantically similar article
        second_article = make_article(
            db_session,
            feed_id=feed.id,
            url="https://source2.com/same-event-different-source",
            title="Same Major Event Covered Differently",
        )
        await db_session.flush()

        # Model returns similar vector for second article
        mock_model_second = make_mock_embed_model(make_similar_vector())

        result = await deduplicate_article(second_article, db_session, mock_model_second, similarity_threshold=0.83)

        # Should return the cluster_id as an integer
        assert isinstance(result, int)
        assert result == cluster.id

    @pytest.mark.asyncio
    async def test_dissimilar_content_returns_new(self, db_session):
        """deduplicate_article with dissimilar content returns 'new' (creates new cluster)."""
        from app.services.deduplicator import deduplicate_article, find_or_create_cluster

        feed = make_feed(db_session)
        await db_session.flush()

        # Create first article and cluster it
        first_article = make_article(
            db_session,
            feed_id=feed.id,
            url="https://source1.com/article-a",
            title="Article About Topic A",
        )
        await db_session.flush()

        mock_model_first = make_mock_embed_model([1.0] + [0.0] * 383)
        await find_or_create_cluster(
            first_article, None, db_session, mock_model_first
        )
        await db_session.flush()

        # Now try to deduplicate a completely different article
        second_article = make_article(
            db_session,
            feed_id=feed.id,
            url="https://source1.com/totally-different",
            title="Completely Different Topic",
        )
        await db_session.flush()

        # Model returns orthogonal vector
        mock_model_dissimilar = make_mock_embed_model(make_dissimilar_vector())

        result = await deduplicate_article(
            second_article, db_session, mock_model_dissimilar, similarity_threshold=0.83
        )

        assert result == "new"

    @pytest.mark.asyncio
    async def test_opinion_not_clustered_with_news(self, db_session):
        """Opinion articles are not clustered with news articles covering the same event."""
        from app.services.deduplicator import deduplicate_article, find_or_create_cluster

        feed = make_feed(db_session)
        await db_session.flush()

        # Create a NEWS article cluster
        news_article = make_article(
            db_session,
            feed_id=feed.id,
            url="https://source1.com/news-about-event",
            title="Breaking: Event Occurs",
            is_opinion=False,
        )
        await db_session.flush()

        mock_model = make_mock_embed_model([1.0] + [0.0] * 383)
        await find_or_create_cluster(news_article, None, db_session, mock_model)
        await db_session.flush()

        # Try to deduplicate an OPINION article with similar embedding
        opinion_article = make_article(
            db_session,
            feed_id=feed.id,
            url="https://source2.com/opinion-about-event",
            title="My Take on the Event",
            is_opinion=True,
        )
        await db_session.flush()

        # Same embedding vector -- semantically similar but different type
        mock_model_opinion = make_mock_embed_model(make_similar_vector())

        result = await deduplicate_article(
            opinion_article, db_session, mock_model_opinion, similarity_threshold=0.83
        )

        # Should NOT join the news cluster -- should be "new"
        assert result == "new"

    @pytest.mark.asyncio
    async def test_similarity_threshold_separates_same_topic(self, db_session):
        """Similarity threshold of 0.83 correctly separates same-event from same-topic stories."""
        from app.services.deduplicator import deduplicate_article, find_or_create_cluster

        feed = make_feed(db_session)
        await db_session.flush()

        # Create a cluster
        first_article = make_article(
            db_session,
            feed_id=feed.id,
            url="https://source1.com/specific-event",
            title="Specific Event in City A",
        )
        await db_session.flush()

        mock_model = make_mock_embed_model([1.0] + [0.0] * 383)
        await find_or_create_cluster(first_article, None, db_session, mock_model)
        await db_session.flush()

        # Article with moderate similarity (below threshold) -- same topic, different event
        same_topic_article = make_article(
            db_session,
            feed_id=feed.id,
            url="https://source2.com/similar-topic-different-event",
            title="Similar Topic But Different Event",
        )
        await db_session.flush()

        # Vector gives cosine sim ~0.70, below 0.83 threshold
        mock_model_moderate = make_mock_embed_model(make_moderate_vector())

        result = await deduplicate_article(
            same_topic_article, db_session, mock_model_moderate, similarity_threshold=0.83
        )

        assert result == "new"


# ---------------------------------------------------------------------------
# Test: find_or_create_cluster
# ---------------------------------------------------------------------------


class TestFindOrCreateCluster:
    """Tests for find_or_create_cluster function."""

    @pytest.mark.asyncio
    async def test_creates_new_cluster_when_no_match(self, db_session):
        """find_or_create_cluster creates new StoryCluster when no match found, sets article as primary."""
        from app.services.deduplicator import find_or_create_cluster

        feed = make_feed(db_session)
        await db_session.flush()

        article = make_article(db_session, feed_id=feed.id)
        await db_session.flush()

        mock_model = make_mock_embed_model()

        cluster = await find_or_create_cluster(
            article, None, db_session, mock_model
        )

        assert cluster is not None
        assert isinstance(cluster, StoryCluster)
        assert cluster.primary_article_id == article.id
        assert cluster.article_count == 1
        assert cluster.status == ClusterStatus.ACTIVE
        assert article.cluster_id == cluster.id

    @pytest.mark.asyncio
    async def test_adds_article_to_existing_cluster(self, db_session):
        """find_or_create_cluster adds article to existing cluster, increments article_count."""
        from app.services.deduplicator import find_or_create_cluster

        feed = make_feed(db_session)
        await db_session.flush()

        # Create first article and cluster
        first_article = make_article(
            db_session,
            feed_id=feed.id,
            url="https://source1.com/first",
            title="First Article",
        )
        await db_session.flush()

        mock_model = make_mock_embed_model()
        cluster = await find_or_create_cluster(
            first_article, None, db_session, mock_model
        )
        await db_session.flush()
        cluster_id = cluster.id

        # Now add second article to same cluster
        second_article = make_article(
            db_session,
            feed_id=feed.id,
            url="https://source2.com/second",
            title="Second Article",
        )
        await db_session.flush()

        updated_cluster = await find_or_create_cluster(
            second_article, cluster_id, db_session, mock_model
        )

        assert updated_cluster.id == cluster_id
        assert updated_cluster.article_count == 2
        assert second_article.cluster_id == cluster_id

    @pytest.mark.asyncio
    async def test_primary_updates_to_higher_trust_tier(self, db_session):
        """Primary article updates to higher trust tier source when new article joins cluster."""
        from app.services.deduplicator import find_or_create_cluster

        # Create low-tier feed and high-tier feed
        low_feed = make_feed(
            db_session,
            name="Low Trust Blog",
            trust_tier=TrustTier.LOW,
        )
        high_feed = make_feed(
            db_session,
            name="Reuters",
            trust_tier=TrustTier.HIGH,
        )
        await db_session.flush()

        # First article from low-tier source
        low_article = make_article(
            db_session,
            feed_id=low_feed.id,
            url=f"https://blog.example.com/article-{low_feed.id}",
            title="Event From Blog",
        )
        await db_session.flush()

        mock_model = make_mock_embed_model()
        cluster = await find_or_create_cluster(
            low_article, None, db_session, mock_model
        )
        await db_session.flush()

        assert cluster.primary_article_id == low_article.id

        # Higher trust article joins
        high_article = make_article(
            db_session,
            feed_id=high_feed.id,
            url=f"https://reuters.com/article-{high_feed.id}",
            title="Same Event From Reuters",
        )
        await db_session.flush()

        updated_cluster = await find_or_create_cluster(
            high_article, cluster.id, db_session, mock_model
        )

        assert updated_cluster.primary_article_id == high_article.id

    @pytest.mark.asyncio
    async def test_primary_does_not_change_for_lower_trust(self, db_session):
        """Primary article does NOT change when new article has lower trust tier."""
        from app.services.deduplicator import find_or_create_cluster

        high_feed = make_feed(
            db_session,
            name="Reuters",
            trust_tier=TrustTier.HIGH,
        )
        low_feed = make_feed(
            db_session,
            name="Blog",
            trust_tier=TrustTier.LOW,
        )
        await db_session.flush()

        # First article from high-tier source
        high_article = make_article(
            db_session,
            feed_id=high_feed.id,
            url=f"https://reuters.com/article-high-{high_feed.id}",
            title="High Trust Article",
        )
        await db_session.flush()

        mock_model = make_mock_embed_model()
        cluster = await find_or_create_cluster(
            high_article, None, db_session, mock_model
        )
        await db_session.flush()

        assert cluster.primary_article_id == high_article.id

        # Lower trust article joins -- primary should NOT change
        low_article = make_article(
            db_session,
            feed_id=low_feed.id,
            url=f"https://blog.example.com/article-low-{low_feed.id}",
            title="Same Event From Blog",
        )
        await db_session.flush()

        updated_cluster = await find_or_create_cluster(
            low_article, cluster.id, db_session, mock_model
        )

        assert updated_cluster.primary_article_id == high_article.id


# ---------------------------------------------------------------------------
# Test: helper functions
# ---------------------------------------------------------------------------


class TestTrustTierRank:
    """Tests for trust tier ranking helper."""

    def test_high_ranks_above_medium(self):
        from app.services.deduplicator import get_feed_trust_tier_rank

        assert get_feed_trust_tier_rank(TrustTier.HIGH) > get_feed_trust_tier_rank(
            TrustTier.MEDIUM
        )

    def test_medium_ranks_above_low(self):
        from app.services.deduplicator import get_feed_trust_tier_rank

        assert get_feed_trust_tier_rank(TrustTier.MEDIUM) > get_feed_trust_tier_rank(
            TrustTier.LOW
        )

    def test_high_is_3_medium_is_2_low_is_1(self):
        from app.services.deduplicator import get_feed_trust_tier_rank

        assert get_feed_trust_tier_rank(TrustTier.HIGH) == 3
        assert get_feed_trust_tier_rank(TrustTier.MEDIUM) == 2
        assert get_feed_trust_tier_rank(TrustTier.LOW) == 1
