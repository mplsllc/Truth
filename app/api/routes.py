"""Web routes for the Truth magazine-style UI."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.article import Article
from app.models.claim import Claim
from app.models.cluster import StoryCluster
from app.models.enums import ClusterStatus, FactCheckStatus
from app.models.feed import Feed

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


def time_ago(dt: datetime | None) -> str:
    """Human-readable time delta."""
    if not dt:
        return ""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        mins = seconds // 60
        return f"{mins}m ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h ago"
    days = seconds // 86400
    return f"{days}d ago"


def score_label(score: float | None) -> str:
    if score is None:
        return "Pending"
    if score >= 0.8:
        return "Well-Sourced"
    if score >= 0.6:
        return "Mostly Verified"
    if score >= 0.4:
        return "Partially Verified"
    return "Poorly Sourced"


def score_class(score: float | None) -> str:
    if score is None:
        return "pending"
    if score >= 0.8:
        return "well-sourced"
    if score >= 0.6:
        return "mostly-verified"
    if score >= 0.4:
        return "partially-verified"
    return "poorly-sourced"


def score_color(score: float | None) -> str:
    if score is None:
        return "#666"
    if score >= 0.8:
        return "#22c55e"
    if score >= 0.6:
        return "#eab308"
    if score >= 0.4:
        return "#f97316"
    return "#ef4444"


async def get_stats(session: AsyncSession) -> dict:
    feed_count = await session.scalar(select(func.count(Feed.id))) or 0
    article_count = await session.scalar(select(func.count(Article.id))) or 0
    return {"feeds": feed_count, "articles": article_count}


TIME_FILTERS = {
    "today": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
}


@router.get("/", response_class=HTMLResponse)
async def homepage(
    request: Request,
    category: str | None = None,
    q: str | None = None,
    period: str | None = None,
):
    async with async_session_factory() as session:
        stats = await get_stats(session)

        # Get categories
        cat_result = await session.execute(
            select(Feed.category).where(Feed.category.isnot(None)).distinct()
        )
        categories = sorted([r[0] for r in cat_result.fetchall()])

        # Build article query for search/time filtering
        if q:
            # Keyword search: find matching articles, then get their clusters
            search_term = f"%{q}%"
            article_query = (
                select(Article.cluster_id)
                .where(
                    Article.cluster_id.isnot(None),
                    or_(
                        Article.title.ilike(search_term),
                        Article.content.ilike(search_term),
                        Article.summary.ilike(search_term),
                    ),
                )
                .distinct()
            )
            matching_ids_result = await session.execute(article_query)
            matching_cluster_ids = [r[0] for r in matching_ids_result.fetchall()]

            query = (
                select(StoryCluster)
                .where(
                    StoryCluster.id.in_(matching_cluster_ids),
                    StoryCluster.status == ClusterStatus.ACTIVE,
                )
                .order_by(StoryCluster.updated_at.desc())
                .limit(50)
            )
        else:
            query = (
                select(StoryCluster)
                .where(StoryCluster.status == ClusterStatus.ACTIVE)
                .order_by(StoryCluster.updated_at.desc())
                .limit(50)
            )

        # Time filtering
        if period and period in TIME_FILTERS:
            cutoff = datetime.now(timezone.utc) - TIME_FILTERS[period]
            query = query.where(StoryCluster.created_at >= cutoff)

        result = await session.execute(query)
        clusters_raw = result.scalars().all()

        clusters = []
        for cluster in clusters_raw:
            if cluster.primary_article_id:
                primary = await session.get(Article, cluster.primary_article_id)
            else:
                primary = cluster.articles[0] if cluster.articles else None

            if not primary:
                continue

            feed = await session.get(Feed, primary.feed_id)

            if category and (not feed or feed.category != category):
                continue

            clusters.append({
                "id": cluster.id,
                "title": cluster.title or primary.title,
                "summary": cluster.summary or primary.summary,
                "image_url": primary.image_url,
                "source_name": feed.name if feed else "Unknown",
                "time_ago": time_ago(primary.published_at or primary.created_at),
                "article_count": cluster.article_count,
                "score": primary.accuracy_score,
                "score_label": score_label(primary.accuracy_score),
                "score_class": score_class(primary.accuracy_score),
                "score_color": score_color(primary.accuracy_score),
                "claim_count": primary.claim_count,
                "published_at": primary.published_at or primary.created_at,
                "has_score": primary.accuracy_score is not None,
            })

        # Boost recent rated stories to the top
        def _sort_key(c):
            age_hours = (datetime.now(timezone.utc) - c["published_at"]).total_seconds() / 3600
            recency = max(0, 1 - age_hours / 72)  # decays over 3 days
            rated_boost = 0.5 if c["has_score"] else 0
            multi_source = min(0.3, c["article_count"] * 0.1)
            return -(recency + rated_boost + multi_source)

        clusters.sort(key=_sort_key)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "stats": stats,
        "clusters": clusters,
        "categories": categories,
        "current_category": category,
        "search_query": q or "",
        "current_period": period or "",
    })


@router.get("/story/{cluster_id}", response_class=HTMLResponse)
async def story_detail(request: Request, cluster_id: int):
    async with async_session_factory() as session:
        stats = await get_stats(session)

        cluster = await session.get(StoryCluster, cluster_id)
        if not cluster:
            return templates.TemplateResponse("base.html", {
                "request": request,
                "stats": stats,
            }, status_code=404)

        # Get primary article
        if cluster.primary_article_id:
            primary = await session.get(Article, cluster.primary_article_id)
        else:
            primary = cluster.articles[0] if cluster.articles else None

        if not primary:
            return templates.TemplateResponse("base.html", {
                "request": request,
                "stats": stats,
            }, status_code=404)

        feed = await session.get(Feed, primary.feed_id)

        # Count verdicts
        claims_result = await session.execute(
            select(Claim).where(Claim.article_id == primary.id)
        )
        claims_raw = claims_result.scalars().all()

        confirmed = sum(1 for c in claims_raw if c.verdict == "confirmed")
        contradicted = sum(1 for c in claims_raw if c.verdict == "contradicted")
        unverifiable = sum(1 for c in claims_raw if c.verdict == "unverifiable")

        primary_data = {
            "url": primary.url,
            "title": primary.title,
            "source_name": feed.name if feed else "Unknown",
            "trust_tier": feed.trust_tier if feed else "medium",
            "time_ago": time_ago(primary.published_at or primary.created_at),
            "score": primary.accuracy_score,
            "score_label": score_label(primary.accuracy_score),
            "score_class": score_class(primary.accuracy_score),
            "score_color": score_color(primary.accuracy_score),
            "claim_count": primary.claim_count,
            "confirmed_count": confirmed,
            "contradicted_count": contradicted,
            "unverifiable_count": unverifiable,
            "content": primary.content,
            "summary": primary.summary,
            "image_url": primary.image_url,
        }

        # Format claims for display
        claims = []
        for c in claims_raw:
            supporting = json.loads(c.supporting_sources) if c.supporting_sources else []
            contradicting = json.loads(c.contradicting_sources) if c.contradicting_sources else []
            claims.append({
                "claim_text": c.claim_text,
                "claim_type": c.claim_type,
                "original_quote": c.original_quote,
                "verdict": c.verdict,
                "confidence": c.confidence,
                "reasoning": c.reasoning,
                "supporting": supporting,
                "contradicting": contradicting,
            })

        # All articles in this cluster
        articles = []
        for article in cluster.articles:
            a_feed = await session.get(Feed, article.feed_id)
            articles.append({
                "url": article.url,
                "title": article.title,
                "source_name": a_feed.name if a_feed else "Unknown",
                "trust_tier": a_feed.trust_tier if a_feed else "medium",
            })

    return templates.TemplateResponse("story.html", {
        "request": request,
        "stats": stats,
        "cluster": {
            "id": cluster.id,
            "title": cluster.title,
            "summary": cluster.summary,
            "article_count": cluster.article_count,
        },
        "primary": primary_data,
        "claims": claims,
        "articles": articles,
    })
