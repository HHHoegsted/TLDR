
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from models import Source

from .fetch import InvalidFeedError, fetch_feed
from .normalize import NormalizationError, normalize_entry
from .persist import persist_article


@dataclass(frozen=True, slots=True)
class IngestionResult:
    source_id: UUID
    status: Literal[
        "processed",
        "not_modified",
        "skipped",
        "failed",
    ]
    http_status: int | None = None
    entries_seen: int = 0
    created: int = 0
    unchanged: int = 0
    updated: int = 0
    raw_updated: int = 0
    conflicts: int = 0
    error: str | None = None


def ingest_source(
    session: Session,
    client: httpx.Client,
    source_id: UUID,
    *,
    now: datetime | None = None,
) -> IngestionResult:
    """Fetch, normalize and persist one configured source.

    The caller owns the database transaction.
    This function never commits.

    Article processing is atomic: if normalization fails,
    all article writes from this ingestion attempt roll back.
    """
    timestamp = (
        datetime.now(timezone.utc)
        if now is None
        else now
    )

    if (
        timestamp.tzinfo is None
        or timestamp.utcoffset() is None
    ):
        raise ValueError("now must be timezone-aware")

    timestamp = timestamp.astimezone(timezone.utc)

    source = session.get(Source, source_id)

    if source is None:
        raise ValueError(
            f"Source does not exist: {source_id}"
        )

    if not source.enabled:
        return IngestionResult(
            source_id=source_id,
            status="skipped",
        )

    try:
        fetched = fetch_feed(
            client,
            source.feed_url,
            etag=source.etag,
            last_modified=source.last_modified,
        )

    except (httpx.HTTPError, InvalidFeedError) as exc:
        message = f"{type(exc).__name__}: {exc}"

        source.last_checked_at = timestamp
        source.last_error = message
        session.flush()

        return IngestionResult(
            source_id=source_id,
            status="failed",
            error=message,
        )

    if fetched.status == "not_modified":
        source.etag = fetched.etag
        source.last_modified = fetched.last_modified
        source.last_checked_at = timestamp
        source.last_success_at = timestamp
        source.last_error = None

        session.flush()

        return IngestionResult(
            source_id=source_id,
            status="not_modified",
            http_status=304,
        )

    counts = {
        "created": 0,
        "unchanged": 0,
        "updated": 0,
        "raw_updated": 0,
        "conflict": 0,
    }

    try:
        # A savepoint prevents partially ingested feeds
        # when an entry cannot be normalized.
        with session.begin_nested():
            for index, entry in enumerate(
                fetched.entries,
                start=1,
            ):
                item = normalize_entry(entry)

                result = persist_article(
                    session,
                    source_id,
                    item,
                    now=timestamp,
                )

                counts[result.status] += 1

    except NormalizationError as exc:
        message = f"Entry {index}: {exc}"

        source.last_checked_at = timestamp
        source.last_error = message

        # Keep the last successful cache validators.
        # The next attempt must be able to retry the feed.
        session.flush()

        return IngestionResult(
            source_id=source_id,
            status="failed",
            http_status=fetched.http_status,
            entries_seen=len(fetched.entries),
            error=message,
        )

    # Only update the cache validators after the
    # complete feed has been processed successfully.
    source.etag = fetched.etag
    source.last_modified = fetched.last_modified
    source.last_checked_at = timestamp
    source.last_success_at = timestamp
    source.last_error = None

    session.flush()

    return IngestionResult(
        source_id=source_id,
        status="processed",
        http_status=fetched.http_status,
        entries_seen=len(fetched.entries),
        created=counts["created"],
        unchanged=counts["unchanged"],
        updated=counts["updated"],
        raw_updated=counts["raw_updated"],
        conflicts=counts["conflict"],
    )
