"""Tests for the fact-check orchestrator."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.article import Article
from app.models.enums import FactCheckStatus
from app.models.feed import Feed
from app.services.fact_checker import age_out_pending, pick_next_article, run_fact_check_cycle


@pytest.mark.asyncio
async def test_age_out_pending(db_session):
    """Articles older than max_age_hours are marked EXPIRED."""
    feed = Feed(name="Test", url="http://test.com/feed", trust_tier="medium")
    db_session.add(feed)
    await db_session.flush()

    old_article = Article(
        url="http://old.com/1",
        url_hash="oldhash1",
        title="Old Article",
        fact_check_status=FactCheckStatus.PENDING,
        feed_id=feed.id,
    )
    # Manually set created_at to 25 hours ago
    old_article.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
    db_session.add(old_article)

    new_article = Article(
        url="http://new.com/1",
        url_hash="newhash1",
        title="New Article",
        fact_check_status=FactCheckStatus.PENDING,
        feed_id=feed.id,
    )
    db_session.add(new_article)
    await db_session.flush()

    count = await age_out_pending(db_session, max_age_hours=24)

    await db_session.refresh(old_article)
    await db_session.refresh(new_article)

    assert count == 1
    assert old_article.fact_check_status == FactCheckStatus.EXPIRED
    assert new_article.fact_check_status == FactCheckStatus.PENDING


@pytest.mark.asyncio
async def test_pick_next_article(db_session):
    """Picks a PENDING article with content."""
    feed = Feed(name="Test", url="http://test2.com/feed", trust_tier="high")
    db_session.add(feed)
    await db_session.flush()

    article = Article(
        url="http://test2.com/article1",
        url_hash="testhash2",
        title="Test Article",
        content="Some article content here.",
        fact_check_status=FactCheckStatus.PENDING,
        feed_id=feed.id,
    )
    db_session.add(article)
    await db_session.flush()

    picked = await pick_next_article(db_session)
    assert picked is not None
    assert picked.id == article.id
    assert picked.fact_check_status == FactCheckStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_pick_next_skips_no_content(db_session):
    """Articles without content are skipped."""
    feed = Feed(name="Test", url="http://test3.com/feed", trust_tier="medium")
    db_session.add(feed)
    await db_session.flush()

    article = Article(
        url="http://test3.com/article1",
        url_hash="testhash3",
        title="No Content",
        content=None,
        fact_check_status=FactCheckStatus.PENDING,
        feed_id=feed.id,
    )
    db_session.add(article)
    await db_session.flush()

    picked = await pick_next_article(db_session)
    assert picked is None


@pytest.mark.asyncio
async def test_pick_next_returns_none_when_empty(db_session):
    """Returns None when no PENDING articles exist."""
    picked = await pick_next_article(db_session)
    assert picked is None


@pytest.mark.asyncio
async def test_run_fact_check_cycle_no_articles(db_session):
    """Cycle with no pending articles returns processed=False."""
    stats = await run_fact_check_cycle(
        session=db_session,
        http_client=AsyncMock(),
        embed_model=MagicMock(),
        ollama_url="http://localhost:11434",
    )
    assert stats["processed"] is False
