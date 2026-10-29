
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .article import Article


class ArticleIdentifier(Base):
    __tablename__ = "article_identifiers"

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "kind",
            "normalized_value",
            name="uq_article_identifier",
        ),
        CheckConstraint(
            "kind IN ('feed_id', 'url')",
            name="ck_article_identifier_kind",
        ),
        ForeignKeyConstraint(
            ["article_id", "source_id"],
            ["articles.id", "articles.source_id"],
            name="fk_article_identifier_article_source",
        ),
    )

    # Identity
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    article_id: Mapped[UUID] = mapped_column(
        index=True,
    )

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id"),
    )

    # Identifier
    kind: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(Text)
    normalized_value: Mapped[str] = mapped_column(Text)

    # Observation timestamps
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Relationships
    article: Mapped[Article] = relationship(
        back_populates="identifiers",
    )
