from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Float, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ClusterStatus

if TYPE_CHECKING:
    from app.models.article import Article


class StoryCluster(Base):
    __tablename__ = "story_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(384), nullable=True
    )
    status: Mapped[ClusterStatus] = mapped_column(
        default=ClusterStatus.ACTIVE, nullable=False
    )
    primary_article_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    article_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_opinion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    composite_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, default=lambda: datetime.now(timezone.utc), server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    articles: Mapped[list[Article]] = relationship(
        "Article", back_populates="cluster", lazy="selectin"
    )

    __table_args__ = (
        Index(
            "ix_cluster_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
