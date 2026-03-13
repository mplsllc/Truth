from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.article import Article


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id"), nullable=False, index=True
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String(50), nullable=False)
    original_quote: Mapped[str] = mapped_column(Text, nullable=False)

    # Verification results (populated by Pass 2)
    verdict: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    confidence: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_sources: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    supporting_sources: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    contradicting_sources: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    article: Mapped[Article] = relationship("Article", back_populates="claims")
