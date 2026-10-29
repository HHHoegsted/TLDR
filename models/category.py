
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .article_category import ArticleCategory


class Category(Base):
    __tablename__ = "categories"

    __table_args__ = (
        UniqueConstraint(
            "scheme",
            "term",
            name="uq_categories_scheme_term",
            postgresql_nulls_not_distinct=True,
        ),
    )

    # Identity
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    # Category metadata
    term: Mapped[str] = mapped_column(Text)

    scheme: Mapped[str | None] = mapped_column(Text)

    label: Mapped[str | None] = mapped_column(Text)

    # Relationships
    article_links: Mapped[list[ArticleCategory]] = relationship(
        back_populates="category",
    )
