
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .article_change import ArticleChange


class ArticleSnapshot(Base):
    __tablename__ = "article_snapshots"

    __table_args__ = (
        UniqueConstraint(
            "change_id",
            name="uq_article_snapshot_change",
        ),
    )

    # Identity
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    # Associated change event
    change_id: Mapped[UUID] = mapped_column(
        ForeignKey("article_changes.id"),
        index=True,
    )

    # Snapshot timestamp
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )

    # Previous raw representation
    raw_entry: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
    )

    # Relationships
    change: Mapped[ArticleChange] = relationship(
        back_populates="snapshot",
    )
