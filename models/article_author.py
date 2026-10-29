
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .article import Article
    from .author import Author


class ArticleAuthor(Base):
    __tablename__ = "article_authors"

    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "position",
            name="uq_article_author_position",
        ),
        CheckConstraint(
            "position >= 0",
            name="ck_article_author_position",
        ),
    )

    # Composite primary key
    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("articles.id"),
        primary_key=True,
    )

    author_id: Mapped[UUID] = mapped_column(
        ForeignKey("authors.id"),
        primary_key=True,
    )

    # Author ordering
    position: Mapped[int] = mapped_column(
        Integer,
    )

    # Relationships
    article: Mapped[Article] = relationship(
        back_populates="author_links",
    )

    author: Mapped[Author] = relationship(
        back_populates="author_links",
    )
