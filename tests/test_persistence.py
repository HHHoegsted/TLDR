
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from ingestion.normalize import normalize_entry
from ingestion.persist import persist_article
from models import (
    Article,
    ArticleAuthor,
    ArticleCategory,
    ArticleChange,
    ArticleIdentifier,
    ArticleSnapshot,
    Author,
    Category,
    IngestionConflict,
    Source,
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


def _source(session):
    source_id = uuid4()

    session.add(
        Source(
            id=source_id,
            name=f"Test {source_id}",
            feed_url=f"https://example.test/{source_id}.xml",
        )
    )

    session.flush()
    return source_id


def _article(
    *,
    guid="guid-123",
    url="https://example.test/article",
    title="Original",
    summary="Original summary",
    extra=None,
    authors=None,
    tags=None,
):
    entry = {
        "link": url,
        "title": title,
        "summary": summary,
    }

    if guid is not None:
        entry["id"] = guid

    if extra is not None:
        entry["extra"] = extra

    if authors is not None:
        entry["authors"] = authors

    if tags is not None:
        entry["tags"] = tags

    return normalize_entry(entry)


def _count(session, model):
    return session.scalar(
        select(func.count()).select_from(model)
    )


def test_create_article_with_identifiers_and_history(db_session):
    source_id = _source(db_session)

    result = persist_article(
        db_session,
        source_id,
        _article(),
    )

    assert result.status == "created"
    assert result.article_id is not None

    article = db_session.get(
        Article,
        result.article_id,
    )

    assert article.title == "Original"
    assert article.summary == "Original summary"
    assert article.raw_entry is not None
    assert _count(db_session, ArticleIdentifier) == 2
    assert _count(db_session, ArticleChange) == 1
    assert _count(db_session, ArticleSnapshot) == 0


def test_reingestion_is_idempotent(db_session):
    source_id = _source(db_session)

    first_time = datetime(
        2026, 10, 29, tzinfo=timezone.utc
    )
    second_time = first_time + timedelta(hours=1)

    item = _article()

    first = persist_article(
        db_session,
        source_id,
        item,
        now=first_time,
    )

    second = persist_article(
        db_session,
        source_id,
        item,
        now=second_time,
    )

    assert first.status == "created"
    assert second.status == "unchanged"
    assert first.article_id == second.article_id
    assert _count(db_session, Article) == 1
    assert _count(db_session, ArticleChange) == 1

    article = db_session.get(Article, first.article_id)

    assert article.last_seen_at == second_time
    assert article.last_changed_at == first_time


def test_content_change_creates_history_and_snapshot(db_session):
    source_id = _source(db_session)

    first = persist_article(
        db_session,
        source_id,
        _article(title="Before"),
    )

    second = persist_article(
        db_session,
        source_id,
        _article(title="After"),
    )

    assert second.status == "updated"
    assert second.article_id == first.article_id

    article = db_session.get(Article, first.article_id)

    assert article.title == "After"

    changes = list(
        db_session.scalars(
            select(ArticleChange).order_by(
                ArticleChange.detected_at,
                ArticleChange.id,
            )
        )
    )

    assert len(changes) == 2
    assert {c.change_type for c in changes} == {
        "created",
        "updated",
    }

    snapshot = db_session.scalar(
        select(ArticleSnapshot)
    )

    assert snapshot is not None
    assert snapshot.raw_entry["title"] == "Before"


def test_raw_only_change_does_not_change_content_hash(db_session):
    source_id = _source(db_session)

    first = persist_article(
        db_session,
        source_id,
        _article(extra="one"),
    )

    original_hash = db_session.get(
        Article,
        first.article_id,
    ).content_hash

    second = persist_article(
        db_session,
        source_id,
        _article(extra="two"),
    )

    assert second.status == "raw_updated"

    article = db_session.get(
        Article,
        first.article_id,
    )

    assert article.content_hash == original_hash
    assert article.raw_entry["extra"] == "two"
    assert _count(db_session, ArticleChange) == 2
    assert _count(db_session, ArticleSnapshot) == 1


def test_same_guid_is_allowed_in_different_sources(db_session):
    source_a = _source(db_session)
    source_b = _source(db_session)

    item = _article()

    first = persist_article(
        db_session,
        source_a,
        item,
    )

    second = persist_article(
        db_session,
        source_b,
        item,
    )

    assert first.status == "created"
    assert second.status == "created"
    assert first.article_id != second.article_id
    assert _count(db_session, Article) == 2


def test_conflicting_identifiers_do_not_merge_articles(db_session):
    source_id = _source(db_session)

    first = persist_article(
        db_session,
        source_id,
        _article(
            guid="guid-a",
            url="https://example.test/a",
        ),
    )

    second = persist_article(
        db_session,
        source_id,
        _article(
            guid="guid-b",
            url="https://example.test/b",
        ),
    )

    conflict = persist_article(
        db_session,
        source_id,
        _article(
            guid="guid-a",
            url="https://example.test/b",
        ),
    )

    assert conflict.status == "conflict"
    assert conflict.article_id is None
    assert conflict.conflict_id is not None

    record = db_session.get(
        IngestionConflict,
        conflict.conflict_id,
    )

    assert record is not None
    assert set(record.candidate_article_ids) == {
        str(first.article_id),
        str(second.article_id),
    }

    assert _count(db_session, Article) == 2
    assert _count(db_session, ArticleIdentifier) == 4


def test_new_guid_can_be_linked_by_known_url(db_session):
    source_id = _source(db_session)

    first = persist_article(
        db_session,
        source_id,
        _article(guid=None),
    )

    second = persist_article(
        db_session,
        source_id,
        _article(guid="new-explicit-guid"),
    )

    assert first.article_id == second.article_id
    assert _count(db_session, Article) == 1
    assert _count(db_session, ArticleIdentifier) == 3


def test_new_url_can_be_linked_by_known_guid(db_session):
    source_id = _source(db_session)

    first = persist_article(
        db_session,
        source_id,
        _article(url="https://example.test/old"),
    )

    second = persist_article(
        db_session,
        source_id,
        _article(url="https://example.test/new"),
    )

    assert first.article_id == second.article_id

    article = db_session.get(
        Article,
        first.article_id,
    )

    assert article.url == "https://example.test/new"
    assert _count(db_session, ArticleIdentifier) == 3


def test_author_and_category_can_be_shared_across_sources(
    db_session,
):
    source_a = _source(db_session)
    source_b = _source(db_session)

    item = _article(
        authors=[
            {
                "name": "Jane Doe",
                "href": "https://example.test/jane",
            }
        ],
        tags=[
            {
                "term": "Python",
                "scheme": "urn:topics",
            }
        ],
    )

    persist_article(db_session, source_a, item)
    persist_article(db_session, source_b, item)

    assert _count(db_session, ArticleAuthor) == 2
    assert _count(db_session, ArticleCategory) == 2
    assert _count(db_session, Author) == 1
    assert _count(db_session, Category) == 1


def test_expired_article_is_not_rehydrated(db_session):
    source_id = _source(db_session)

    start = datetime(
        2026, 8, 1, tzinfo=timezone.utc
    )

    first = persist_article(
        db_session,
        source_id,
        _article(title="Original"),
        now=start,
    )

    result = persist_article(
        db_session,
        source_id,
        _article(title="Updated"),
        now=start + timedelta(days=31),
    )

    assert result.status == "updated"

    article = db_session.get(
        Article,
        first.article_id,
    )

    assert article.title == "Updated"
    assert article.summary is None
    assert article.content_html is None
    assert article.content_text is None
    assert article.raw_entry is None
    assert _count(db_session, ArticleSnapshot) == 0


def test_protected_article_retains_payload(db_session):
    source_id = _source(db_session)

    start = datetime(
        2026, 8, 1, tzinfo=timezone.utc
    )

    first = persist_article(
        db_session,
        source_id,
        _article(title="Original"),
        now=start,
    )

    article = db_session.get(
        Article,
        first.article_id,
    )
    article.protected_at = start

    persist_article(
        db_session,
        source_id,
        _article(title="Updated"),
        now=start + timedelta(days=31),
    )

    assert article.title == "Updated"
    assert article.summary == "Original summary"
    assert article.raw_entry is not None
    assert _count(db_session, ArticleSnapshot) == 1
