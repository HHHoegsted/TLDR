
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class IngestionConflict(Base):
    __tablename__ = "ingestion_conflicts"

    # Identity
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id"),
        index=True,
    )

    # Conflict information
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    reason: Mapped[str] = mapped_column(Text)

    identifiers: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
    )

    candidate_article_ids: Mapped[list[str]] = mapped_column(
        JSONB,
    )

    # Original incoming feed entry
    raw_entry: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
    )

    # Resolution
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    resolved_by: Mapped[str | None] = mapped_column(Text)

    resolution_note: Mapped[str | None] = mapped_column(Text)
