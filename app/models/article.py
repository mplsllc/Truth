from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import FactCheckStatus

if TYPE_CHECKING:
    from app.models.claim import Claim
    from app.models.cluster import StoryCluster
    from app.models.feed import Feed


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False)
    url_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    author: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    is_opinion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_wire_story: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    wire_source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    fact_check_status: Mapped[FactCheckStatus] = mapped_column(
        String(20), default=FactCheckStatus.PENDING, nullable=False
    )
    accuracy_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fact_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fact_check_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    claim_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cluster_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("story_clusters.id"), nullable=True
    )
    feed_id: Mapped[int] = mapped_column(
        ForeignKey("feeds.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )

    cluster: Mapped[Optional[StoryCluster]] = relationship(
        "StoryCluster", back_populates="articles"
    )
    feed: Mapped[Feed] = relationship("Feed", back_populates="articles")
    claims: Mapped[list[Claim]] = relationship(
        "Claim", back_populates="article", lazy="selectin"
    )
