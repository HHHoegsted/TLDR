
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from xml.sax.saxutils import escape

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from ingestion import ingest_source
from models import (
    Article,
    ArticleChange,
    ArticleIdentifier,
    ArticleSnapshot,
    IngestionConflict,
    Source,
)


NOW = datetime(
    2026, 10, 29, 12, 0, tzinfo=timezone.utc
)


@pytest.fixture
def db_session():
    url = os.getenv("DATABASE_URL")

    if not url:
        pytest.skip("DATABASE_URL is not configured")

    engine = create_engine(url)

    try:
        with engine.connect() as connection:
            transaction = connection.begin()

            session = Session(
                bind=connection,
                join_transaction_mode="create_savepoint",
            )

            try:
                yield session
            finally:
                session.close()
                transaction.rollback()
    finally:
        engine.dispose()


def _source(session, *, enabled=True):
    source_id = uuid4()

    session.add(
        Source(
            id=source_id,
            name=f"Feed {source_id}",
            feed_url=f"https://example.test/{source_id}.rss",
            enabled=enabled,
        )
    )

    session.flush()
    return source_id


def _item(guid, title, url):
    return f"""
    <item>
      <guid isPermaLink="false">{escape(guid)}</guid>
      <title>{escape(title)}</title>
      <link>{escape(url)}</link>
      <description>News summary</description>
    </item>
    """


def _feed(*items):
    return f"""<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <title>TLDR Test</title>
        <link>https://example.test/</link>
        <description>Test news</description>
        {''.join(items)}
      </channel>
    </rss>
    """.encode("utf-8")


def _response(content, *, etag=None):
    headers = {
        "Content-Type": "application/rss+xml",
    }

    if etag:
        headers["ETag"] = etag

    return httpx.Response(
        200,
        content=content,
        headers=headers,
    )


def _client(handler):
    return httpx.Client(
        transport=httpx.MockTransport(handler)
    )


def _count(session, model):
    return session.scalar(
        select(func.count()).select_from(model)
    )


def test_processes_feed_and_updates_source(db_session):
    source_id = _source(db_session)

    payload = _feed(
        _item(
            "guid-a",
            "Article A",
            "https://example.test/a",
        ),
        _item(
            "guid-b",
            "Article B",
            "https://example.test/b",
        ),
    )

    with _client(
        lambda request: _response(
            payload,
            etag='"feed-v1"',
        )
    ) as client:
        result = ingest_source(
            db_session,
            client,
            source_id,
            now=NOW,
        )

    assert result.status == "processed"
    assert result.http_status == 200
    assert result.entries_seen == 2
    assert result.created == 2
    assert result.conflicts == 0

    assert _count(db_session, Article) == 2
    assert _count(db_session, ArticleIdentifier) == 4
    assert _count(db_session, ArticleChange) == 2

    source = db_session.get(Source, source_id)

    assert source.etag == '"feed-v1"'
    assert source.last_checked_at == NOW
    assert source.last_success_at == NOW
    assert source.last_error is None


def test_repeated_feed_does_not_duplicate_articles(
    db_session,
):
    source_id = _source(db_session)

    payload = _feed(
        _item(
            "guid-a",
            "Article A",
            "https://example.test/a",
        ),
    )

    with _client(
        lambda request: _response(payload)
    ) as client:
        first = ingest_source(
            db_session,
            client,
            source_id,
            now=NOW,
        )

        second = ingest_source(
            db_session,
            client,
            source_id,
            now=NOW + timedelta(hours=1),
        )

    assert first.created == 1
    assert second.unchanged == 1
    assert second.created == 0

    assert _count(db_session, Article) == 1
    assert _count(db_session, ArticleChange) == 1


def test_304_uses_cache_validators(db_session):
    source_id = _source(db_session)
    source = db_session.get(Source, source_id)

    source.etag = '"old-etag"'
    source.last_modified = (
        "Thu, 29 Oct 2026 10:00:00 GMT"
    )
    source.last_error = "Previous failure"

    def handler(request):
        assert (
            request.headers["if-none-match"]
            == '"old-etag"'
        )
        assert (
            request.headers["if-modified-since"]
            == "Thu, 29 Oct 2026 10:00:00 GMT"
        )

        return httpx.Response(304)

    with _client(handler) as client:
        result = ingest_source(
            db_session,
            client,
            source_id,
            now=NOW,
        )

    assert result.status == "not_modified"
    assert result.http_status == 304
    assert result.entries_seen == 0

    assert source.etag == '"old-etag"'
    assert source.last_checked_at == NOW
    assert source.last_success_at == NOW
    assert source.last_error is None

    assert _count(db_session, Article) == 0


def test_disabled_source_is_not_fetched(db_session):
    source_id = _source(
        db_session,
        enabled=False,
    )

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200)

    with _client(handler) as client:
        result = ingest_source(
            db_session,
            client,
            source_id,
            now=NOW,
        )

    assert result.status == "skipped"
    assert requests == []

    source = db_session.get(Source, source_id)
    assert source.last_checked_at is None


def test_unknown_source_is_rejected(db_session):
    with _client(
        lambda request: pytest.fail(
            "HTTP must not be called"
        )
    ) as client:
        with pytest.raises(
            ValueError,
            match="Source does not exist",
        ):
            ingest_source(
                db_session,
                client,
                uuid4(),
                now=NOW,
            )


def test_http_failure_preserves_cache(db_session):
    source_id = _source(db_session)
    source = db_session.get(Source, source_id)

    source.etag = '"last-good"'

    with _client(
        lambda request: httpx.Response(503)
    ) as client:
        result = ingest_source(
            db_session,
            client,
            source_id,
            now=NOW,
        )

    assert result.status == "failed"
    assert "HTTPStatusError" in result.error

    assert source.etag == '"last-good"'
    assert source.last_checked_at == NOW
    assert source.last_success_at is None
    assert source.last_error is not None

    assert _count(db_session, Article) == 0


def test_malformed_feed_is_recorded_as_failure(
    db_session,
):
    source_id = _source(db_session)

    with _client(
        lambda request: _response(
            b"<rss><channel></rss>"
        )
    ) as client:
        result = ingest_source(
            db_session,
            client,
            source_id,
            now=NOW,
        )

    assert result.status == "failed"
    assert "InvalidFeedError" in result.error
    assert _count(db_session, Article) == 0

    source = db_session.get(Source, source_id)

    assert source.last_error is not None
    assert source.last_success_at is None


def test_invalid_entry_rolls_back_entire_feed(
    db_session,
):
    source_id = _source(db_session)

    source = db_session.get(Source, source_id)
    source.etag = '"previous-good"'

    payload = _feed(
        _item(
            "valid-guid",
            "Valid article",
            "https://example.test/valid",
        ),
        "<item><title>No identity</title></item>",
    )

    with _client(
        lambda request: _response(
            payload,
            etag='"new-etag"',
        )
    ) as client:
        result = ingest_source(
            db_session,
            client,
            source_id,
            now=NOW,
        )

    assert result.status == "failed"
    assert result.entries_seen == 2
    assert "Entry 2" in result.error

    # The first article must also have rolled back.
    assert _count(db_session, Article) == 0
    assert _count(db_session, ArticleChange) == 0

    assert source.etag == '"previous-good"'
    assert source.last_success_at is None
    assert source.last_checked_at == NOW


def test_changed_article_creates_history(db_session):
    source_id = _source(db_session)

    original = _feed(
        _item(
            "guid-a",
            "Original title",
            "https://example.test/a",
        ),
    )

    updated = _feed(
        _item(
            "guid-a",
            "Updated title",
            "https://example.test/a",
        ),
    )

    responses = iter([
        _response(original, etag='"v1"'),
        _response(updated, etag='"v2"'),
    ])

    with _client(
        lambda request: next(responses)
    ) as client:
        first = ingest_source(
            db_session,
            client,
            source_id,
            now=NOW,
        )

        second = ingest_source(
            db_session,
            client,
            source_id,
            now=NOW + timedelta(hours=1),
        )

    assert first.created == 1
    assert second.updated == 1

    assert _count(db_session, Article) == 1
    assert _count(db_session, ArticleChange) == 2
    assert _count(db_session, ArticleSnapshot) == 1

    article = db_session.scalar(
        select(Article)
    )

    assert article.title == "Updated title"

    source = db_session.get(Source, source_id)
    assert source.etag == '"v2"'


def test_identity_conflict_does_not_merge_articles(
    db_session,
):
    source_id = _source(db_session)

    original = _feed(
        _item(
            "guid-a",
            "Article A",
            "https://example.test/a",
        ),
        _item(
            "guid-b",
            "Article B",
            "https://example.test/b",
        ),
    )

    conflicting = _feed(
        _item(
            "guid-a",
            "Ambiguous article",
            "https://example.test/b",
        ),
    )

    responses = iter([
        _response(original),
        _response(conflicting),
    ])

    with _client(
        lambda request: next(responses)
    ) as client:
        first = ingest_source(
            db_session,
            client,
            source_id,
            now=NOW,
        )

        second = ingest_source(
            db_session,
            client,
            source_id,
            now=NOW + timedelta(hours=1),
        )

    assert first.created == 2
    assert second.conflicts == 1
    assert second.created == 0

    assert _count(db_session, Article) == 2
    assert _count(db_session, IngestionConflict) == 1


def test_successful_200_clears_old_cache_validators(
    db_session,
):
    source_id = _source(db_session)

    source = db_session.get(Source, source_id)
    source.etag = '"old"'
    source.last_modified = (
        "Thu, 29 Oct 2026 10:00:00 GMT"
    )

    with _client(
        lambda request: _response(_feed())
    ) as client:
        result = ingest_source(
            db_session,
            client,
            source_id,
            now=NOW,
        )

    assert result.status == "processed"
    assert result.entries_seen == 0

    assert source.etag is None
    assert source.last_modified is None
    assert source.last_success_at == NOW


def test_ingestion_does_not_commit(db_session, monkeypatch):
    source_id = _source(db_session)

    def forbidden_commit():
        pytest.fail(
            "ingest_source must not call session.commit()"
        )

    monkeypatch.setattr(
        db_session,
        "commit",
        forbidden_commit,
    )

    payload = _feed(
        _item(
            "guid-a",
            "Article A",
            "https://example.test/a",
        ),
    )

    with _client(
        lambda request: _response(payload)
    ) as client:
        result = ingest_source(
            db_session,
            client,
            source_id,
            now=NOW,
        )

    assert result.status == "processed"
    assert result.created == 1
