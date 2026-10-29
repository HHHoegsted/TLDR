
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .article_author import ArticleAuthor
    from .article_category import ArticleCategory
    from .article_change import ArticleChange
    from .article_identifier import ArticleIdentifier


class Article(Base):
    __tablename__ = "articles"

    __table_args__ = (
        UniqueConstraint(
            "id",
            "source_id",
            name="uq_articles_id_source",
        ),
    )

    # Identity
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id"),
        index=True,
    )

    # Metadata
    url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(35))

    # Content
    summary: Mapped[str | None] = mapped_column(Text)
    content_html: Mapped[str | None] = mapped_column(Text)
    content_text: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(100))

    # Publisher timestamps
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    feed_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # Ingestion timestamps
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    last_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # Source representation
    raw_entry: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB
    )

    # Change detection
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_hash: Mapped[str] = mapped_column(String(64))

    # Retention protection
    protected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    protected_by: Mapped[str | None] = mapped_column(Text)
    protection_reason: Mapped[str | None] = mapped_column(Text)

    # Relationships
    identifiers: Mapped[list[ArticleIdentifier]] = relationship(
        back_populates="article",
    )

    changes: Mapped[list[ArticleChange]] = relationship(
        back_populates="article",
        order_by="ArticleChange.detected_at",
    )

    author_links: Mapped[list[ArticleAuthor]] = relationship(
        back_populates="article",
        order_by="ArticleAuthor.position",
    )

    category_links: Mapped[list[ArticleCategory]] = relationship(
        back_populates="article",
    )
