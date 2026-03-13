"""Three-tier evidence gathering for claim verification."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.cluster import StoryCluster
from app.models.enums import ClusterStatus
from app.services.deduplicator import embed_text
from app.services.wikipedia_client import query_wikidata, search_wikipedia

log = structlog.get_logger()

MAX_EVIDENCE_ITEMS = 5
MAX_PASSAGE_CHARS = 1500


@dataclass
class EvidenceItem:
    source_name: str
    source_url: str
    text: str
    trust_tier: str
    tier_source: str  # "cluster", "semantic", "wikipedia", "wikidata"


@dataclass
class EvidenceBundle:
    items: list[EvidenceItem] = field(default_factory=list)
    cluster_count: int = 0
    semantic_count: int = 0
    external_count: int = 0


async def get_cluster_evidence(
    article: Article,
    session: AsyncSession,
) -> list[EvidenceItem]:
    """Tier 1: Get evidence from articles in the same story cluster."""
    if not article.cluster_id:
        return []

    cluster = await session.get(StoryCluster, article.cluster_id)
    if not cluster:
        return []

    # Eagerly load cluster articles to avoid lazy-load in async context
    from app.models.feed import Feed
    result = await session.execute(
        select(Article).where(
            Article.cluster_id == article.cluster_id,
            Article.id != article.id,
            Article.content.isnot(None),
        )
    )
    other_articles = result.scalars().all()

    items = []
    for other in other_articles:
        feed = await session.get(Feed, other.feed_id)
        items.append(EvidenceItem(
            source_name=feed.name if feed else "Unknown",
            source_url=other.url,
            text=other.content[:MAX_PASSAGE_CHARS],
            trust_tier=feed.trust_tier if feed else "low",
            tier_source="cluster",
        ))

    await log.ainfo("cluster_evidence", article_id=article.id, items=len(items))
    return items


async def get_semantic_evidence(
    article: Article,
    session: AsyncSession,
    embed_model: Any,
) -> list[EvidenceItem]:
    """Tier 2: Get evidence from semantically similar articles via pgvector."""
    embed_input = article.title + " " + (article.summary or "")[:500]
    embedding = embed_text(embed_input, embed_model)

    try:
        result = await session.execute(
            text("""
                SELECT a.id, a.title, a.content, a.url, f.name, f.trust_tier,
                       1 - (sc.embedding <=> :embedding) as similarity
                FROM articles a
                JOIN story_clusters sc ON a.cluster_id = sc.id
                JOIN feeds f ON a.feed_id = f.id
                WHERE a.id != :article_id
                  AND a.content IS NOT NULL
                  AND sc.status = :status
                ORDER BY similarity DESC
                LIMIT 3
            """),
            {
                "embedding": str(embedding),
                "article_id": article.id,
                "status": ClusterStatus.ACTIVE.value,
            },
        )
        rows = result.fetchall()
    except Exception:
        # SQLite fallback — skip semantic evidence
        return []

    items = []
    for row in rows:
        items.append(EvidenceItem(
            source_name=row[4],
            source_url=row[3],
            text=(row[2] or "")[:MAX_PASSAGE_CHARS],
            trust_tier=row[5],
            tier_source="semantic",
        ))

    await log.ainfo("semantic_evidence", article_id=article.id, items=len(items))
    return items


async def get_external_evidence(
    article: Article,
    http_client,
) -> list[EvidenceItem]:
    """Tier 3: Get evidence from Wikipedia and Wikidata."""
    query = article.title
    items = []

    try:
        wiki_results, wikidata_results = await asyncio.gather(
            search_wikipedia(query, http_client, limit=2),
            query_wikidata(query, http_client),
            return_exceptions=True,
        )

        if isinstance(wiki_results, list):
            for result in wiki_results:
                items.append(EvidenceItem(
                    source_name=f"Wikipedia: {result['title']}",
                    source_url=f"https://en.wikipedia.org/wiki/{result['title'].replace(' ', '_')}",
                    text=result["extract"][:MAX_PASSAGE_CHARS],
                    trust_tier="high",
                    tier_source="wikipedia",
                ))

        if isinstance(wikidata_results, list) and wikidata_results:
            facts = "; ".join(f"{r['property']}: {r['value']}" for r in wikidata_results[:10])
            items.append(EvidenceItem(
                source_name="Wikidata",
                source_url="https://www.wikidata.org",
                text=facts[:MAX_PASSAGE_CHARS],
                trust_tier="high",
                tier_source="wikidata",
            ))
    except Exception as e:
        await log.awarn("external_evidence_failed", error=str(e))

    await log.ainfo("external_evidence", article_id=article.id, items=len(items))
    return items


async def gather_evidence(
    article: Article,
    session: AsyncSession,
    embed_model: Any,
    http_client,
) -> EvidenceBundle:
    """Gather evidence from all three tiers concurrently.

    Returns at most MAX_EVIDENCE_ITEMS items, prioritizing cluster > semantic > external.
    """
    # Run DB operations sequentially (shared session), external in parallel
    try:
        cluster_items = await get_cluster_evidence(article, session)
    except Exception as e:
        await log.awarn("cluster_evidence_error", error=str(e))
        cluster_items = []

    try:
        semantic_items = await get_semantic_evidence(article, session, embed_model)
    except Exception as e:
        await log.awarn("semantic_evidence_error", error=str(e))
        semantic_items = []

    try:
        external_items = await get_external_evidence(article, http_client)
    except Exception as e:
        await log.awarn("external_evidence_error", error=str(e))
        external_items = []

    # Combine with priority: cluster > semantic > external
    all_items = cluster_items + semantic_items + external_items
    limited = all_items[:MAX_EVIDENCE_ITEMS]

    bundle = EvidenceBundle(
        items=limited,
        cluster_count=len(cluster_items),
        semantic_count=len(semantic_items),
        external_count=len(external_items),
    )

    await log.ainfo(
        "evidence_gathered",
        article_id=article.id,
        total=len(limited),
        cluster=bundle.cluster_count,
        semantic=bundle.semantic_count,
        external=bundle.external_count,
    )
    return bundle
