
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .article import Article
    from .category import Category


class ArticleCategory(Base):
    __tablename__ = "article_categories"

    # Composite primary key
    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("articles.id"),
        primary_key=True,
    )

    category_id: Mapped[UUID] = mapped_column(
        ForeignKey("categories.id"),
        primary_key=True,
    )

    # Relationships
    article: Mapped[Article] = relationship(
        back_populates="category_links",
    )

    category: Mapped[Category] = relationship(
        back_populates="article_links",
    )
