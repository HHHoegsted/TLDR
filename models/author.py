
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .article_author import ArticleAuthor


class Author(Base):
    __tablename__ = "authors"

    # Identity
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    # Author metadata
    name: Mapped[str] = mapped_column(Text)

    uri: Mapped[str | None] = mapped_column(Text)

    # Relationships
    author_links: Mapped[list[ArticleAuthor]] = relationship(
        back_populates="author",
    )
