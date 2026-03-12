"""Two-phase deduplication service: URL hash + pgvector semantic similarity.

Phase 1: Fast URL hash check catches exact duplicate URLs in O(1).
Phase 2: Sentence-transformers embedding + pgvector cosine similarity
clusters same-event articles from different sources at 0.83 threshold.

Opinion pieces are clustered separately from news coverage.
Primary article in each cluster is the one from the highest trust tier source.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.article import Article
from app.models.cluster import StoryCluster
from app.models.enums import ClusterStatus, TrustTier
from app.models.feed import Feed

logger = structlog.get_logger(__name__)


def get_feed_trust_tier_rank(tier: TrustTier) -> int:
    """Convert trust tier to numeric rank for comparison.

    HIGH=3, MEDIUM=2, LOW=1. Higher is more trusted.
    """
    return {TrustTier.HIGH: 3, TrustTier.MEDIUM: 2, TrustTier.LOW: 1}.get(tier, 0)


def embed_text(text_content: str, model: Any) -> list[float]:
    """Generate a 384-dim embedding from text using sentence-transformers model.

    Args:
        text_content: Text to embed (title + summary).
        model: sentence-transformers SentenceTransformer instance.

    Returns:
        List of floats representing the embedding vector.
    """
    embedding = model.encode(text_content)
    # Convert numpy array to list if needed
    if hasattr(embedding, "tolist"):
        return embedding.tolist()
    return list(embedding)


async def deduplicate_article(
    article: Article,
    session: AsyncSession,
    embed_model: Any,
    similarity_threshold: float | None = None,
) -> str | int:
    """Two-phase deduplication for an article.

    Phase 1 - URL hash check: exact duplicate detection.
    Phase 2 - Semantic similarity: cluster matching via pgvector cosine similarity.

    Args:
        article: The Article to deduplicate.
        session: Async database session.
        embed_model: sentence-transformers model for embedding generation.

    Returns:
        "duplicate" if exact URL match found.
        "new" if no similar cluster found.
        cluster_id (int) if semantically similar cluster found.
    """
    log = logger.bind(article_url=article.url, article_title=article.title)

    # Phase 1: URL hash check
    query = select(Article.id).where(Article.url_hash == article.url_hash)
    if article.id is not None:
        query = query.where(Article.id != article.id)
    existing = await session.execute(query)
    if existing.scalar_one_or_none() is not None:
        await log.ainfo("dedup_url_match", result="duplicate")
        return "duplicate"

    # Phase 2: Semantic similarity via embeddings
    if similarity_threshold is None:
        settings = get_settings()
        threshold = settings.dedup_similarity_threshold
    else:
        threshold = similarity_threshold

    # Generate embedding for the article
    embed_input = article.title + " " + (article.summary or "")[:500]
    embedding = embed_text(embed_input, embed_model)

    # Query for similar active clusters
    # For SQLite tests, we skip pgvector queries and return "new"
    try:
        result = await session.execute(
            text(
                """
                SELECT id, is_opinion, 1 - (embedding <=> :embedding) as similarity
                FROM story_clusters
                WHERE status = :status
                ORDER BY similarity DESC
                LIMIT 5
                """
            ),
            {
                "embedding": str(embedding),
                "status": ClusterStatus.ACTIVE.value,
            },
        )
        rows = result.fetchall()
    except Exception:
        # SQLite or other backends without pgvector -- fallback to in-memory comparison
        rows = await _fallback_similarity_search(
            embedding, session, threshold, article.is_opinion
        )
        if rows:
            cluster_id = rows[0]
            await log.ainfo("dedup_semantic_match", cluster_id=cluster_id)
            return cluster_id
        await log.ainfo("dedup_no_match", result="new")
        return "new"

    # Filter by threshold and opinion match
    for row in rows:
        cluster_id = row[0]
        cluster_is_opinion = row[1]
        similarity = row[2]

        if similarity < threshold:
            continue

        # Opinion/news separation: skip if opinion status doesn't match
        if bool(cluster_is_opinion) != bool(article.is_opinion):
            await log.ainfo(
                "dedup_opinion_mismatch",
                cluster_id=cluster_id,
                similarity=similarity,
            )
            continue

        await log.ainfo(
            "dedup_semantic_match",
            cluster_id=cluster_id,
            similarity=similarity,
        )
        return cluster_id

    await log.ainfo("dedup_no_match", result="new")
    return "new"


async def _fallback_similarity_search(
    embedding: list[float],
    session: AsyncSession,
    threshold: float,
    is_opinion: bool,
) -> list[int]:
    """Fallback similarity search for non-pgvector backends (e.g., SQLite in tests).

    Computes cosine similarity in Python against stored cluster embeddings.

    Returns:
        List of cluster IDs that match (above threshold, matching opinion status).
    """
    clusters = await session.execute(
        select(StoryCluster).where(StoryCluster.status == ClusterStatus.ACTIVE)
    )
    matches = []

    for cluster in clusters.scalars().all():
        if cluster.embedding is None:
            continue

        # Parse stored embedding (stored as text in SQLite)
        stored_embedding = cluster.embedding
        if isinstance(stored_embedding, str):
            import json

            try:
                stored_embedding = json.loads(stored_embedding)
            except (json.JSONDecodeError, TypeError):
                continue

        # Compute cosine similarity
        sim = _cosine_similarity(embedding, stored_embedding)

        if sim >= threshold and bool(cluster.is_opinion) == bool(is_opinion):
            matches.append((cluster.id, sim))

    # Sort by similarity descending
    matches.sort(key=lambda x: x[1], reverse=True)
    return [m[0] for m in matches]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def find_or_create_cluster(
    article: Article,
    cluster_id: int | None,
    session: AsyncSession,
    embed_model: Any,
) -> StoryCluster:
    """Create a new cluster or add article to existing cluster.

    When creating: sets article as primary, article_count=1.
    When joining: increments article_count, promotes primary if new article
    has higher trust tier.

    Args:
        article: The Article to cluster.
        cluster_id: Existing cluster ID (None = create new).
        session: Async database session.
        embed_model: sentence-transformers model for embedding generation.

    Returns:
        The StoryCluster (new or updated).
    """
    log = logger.bind(article_id=article.id, cluster_id=cluster_id)

    # Generate embedding for cluster
    embed_input = article.title + " " + (article.summary or "")[:500]
    embedding = embed_text(embed_input, embed_model)

    if cluster_id is None:
        # Create new cluster
        import json

        cluster = StoryCluster(
            embedding=json.dumps(embedding),  # Store as text for SQLite compat
            status=ClusterStatus.ACTIVE,
            primary_article_id=article.id,
            article_count=1,
            is_opinion=article.is_opinion,
        )
        session.add(cluster)
        await session.flush()

        article.cluster_id = cluster.id
        await session.flush()

        await log.ainfo(
            "cluster_created",
            new_cluster_id=cluster.id,
            is_opinion=article.is_opinion,
        )
        return cluster

    # Join existing cluster
    cluster = await session.get(StoryCluster, cluster_id)
    if cluster is None:
        raise ValueError(f"Cluster {cluster_id} not found")

    article.cluster_id = cluster.id
    cluster.article_count += 1

    # Check trust tier promotion
    article_feed = await session.get(Feed, article.feed_id)
    if article_feed and cluster.primary_article_id:
        current_primary = await session.get(Article, cluster.primary_article_id)
        if current_primary:
            current_primary_feed = await session.get(Feed, current_primary.feed_id)
            if current_primary_feed:
                new_rank = get_feed_trust_tier_rank(article_feed.trust_tier)
                current_rank = get_feed_trust_tier_rank(
                    current_primary_feed.trust_tier
                )
                if new_rank > current_rank:
                    cluster.primary_article_id = article.id
                    await log.ainfo(
                        "cluster_primary_promoted",
                        new_primary_id=article.id,
                        old_tier=current_primary_feed.trust_tier.value,
                        new_tier=article_feed.trust_tier.value,
                    )

    await session.flush()

    await log.ainfo(
        "cluster_joined",
        article_count=cluster.article_count,
    )
    return cluster
