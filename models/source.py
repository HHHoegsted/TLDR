
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Source(Base):
    __tablename__ = "sources"

    # Identity
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    # Source configuration
    name: Mapped[str] = mapped_column(Text)

    feed_url: Mapped[str] = mapped_column(Text)

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        server_default=true(),
    )

    # HTTP cache validation
    etag: Mapped[str | None] = mapped_column(Text)

    last_modified: Mapped[str | None] = mapped_column(Text)

    # Ingestion monitoring
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    last_error: Mapped[str | None] = mapped_column(Text)
