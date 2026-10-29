
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .article import Article
    from .article_snapshot import ArticleSnapshot


class ArticleChange(Base):
    __tablename__ = "article_changes"

    # Identity
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("articles.id"),
        index=True,
    )

    # Event
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    change_type: Mapped[str] = mapped_column(String(32))

    # Compact change metadata - no article content
    changes: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
    )

    # Content hashes
    previous_content_hash: Mapped[str | None] = mapped_column(
        String(64)
    )

    new_content_hash: Mapped[str | None] = mapped_column(
        String(64)
    )

    # Raw source hashes
    previous_raw_hash: Mapped[str | None] = mapped_column(
        String(64)
    )

    new_raw_hash: Mapped[str | None] = mapped_column(
        String(64)
    )

    # Relationships
    article: Mapped[Article] = relationship(
        back_populates="changes",
    )

    snapshot: Mapped[ArticleSnapshot | None] = relationship(
        back_populates="change",
        uselist=False,
    )
