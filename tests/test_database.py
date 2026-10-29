
import os
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import (
    create_engine,
    func,
    insert,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from models import (
    Article,
    ArticleAuthor,
    ArticleCategory,
    ArticleChange,
    ArticleIdentifier,
    ArticleSnapshot,
    Author,
    Base,
    Category,
    Source,
)


# ---------------------------------------------------------
# Fixtures
# ---------------------------------------------------------


@pytest.fixture(scope="module")
def db_engine():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        pytest.skip("DATABASE_URL is not configured")

    engine = create_engine(database_url)

    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_tx(db_engine: Engine):
    """Provide a rollback-only database transaction."""
    with db_engine.connect() as connection:
        transaction = connection.begin()

        try:
            yield connection
        finally:
            transaction.rollback()


# ---------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------


def _create_test_source(connection):
    """Create a valid Source within the active transaction."""
    source_id = uuid4()

    connection.execute(
        insert(Source).values(
            id=source_id,
            name=f"Test Source {source_id}",
            feed_url=f"https://example.test/{source_id}.rss",
        )
    )

    return source_id


def _create_test_article(connection, source_id=None):
    """Create a source and article unless a source is supplied."""
    if source_id is None:
        source_id = _create_test_source(connection)

    article_id = uuid4()

    connection.execute(
        insert(Article).values(
            id=article_id,
            source_id=source_id,
            content_hash="a" * 64,
            raw_hash="b" * 64,
        )
    )

    return source_id, article_id


# ---------------------------------------------------------
# Database schema
# ---------------------------------------------------------


def test_database_tables(db_engine: Engine):
    inspector = inspect(db_engine)

    actual_tables = set(inspector.get_table_names())

    expected_tables = set(Base.metadata.tables)
    expected_tables.add("alembic_version")

    assert actual_tables == expected_tables


def test_database_migration_version(db_engine: Engine):
    alembic_config = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_config)

    heads = script.get_heads()

    assert len(heads) == 1

    with db_engine.connect() as connection:
        version = connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )

    assert version == heads[0]


# ---------------------------------------------------------
# Source
# ---------------------------------------------------------


def test_source_enabled_defaults_to_true(db_tx):
    source_id = _create_test_source(db_tx)

    enabled = db_tx.scalar(
        select(Source.enabled).where(Source.id == source_id)
    )

    assert enabled is True


def test_source_can_be_disabled(db_tx):
    source_id = _create_test_source(db_tx)

    db_tx.execute(
        update(Source)
        .where(Source.id == source_id)
        .values(enabled=False)
    )

    enabled = db_tx.scalar(
        select(Source.enabled).where(Source.id == source_id)
    )

    assert enabled is False


# ---------------------------------------------------------
# ArticleIdentifier
# ---------------------------------------------------------


def test_article_identifier_uniqueness(db_tx):
    source_a = _create_test_source(db_tx)
    source_b = _create_test_source(db_tx)

    _, article_a = _create_test_article(db_tx, source_a)
    _, article_b = _create_test_article(db_tx, source_a)
    _, article_c = _create_test_article(db_tx, source_b)

    # Same GUID in different sources is allowed.
    for article_id, source_id in (
        (article_a, source_a),
        (article_c, source_b),
    ):
        db_tx.execute(
            insert(ArticleIdentifier).values(
                id=uuid4(),
                article_id=article_id,
                source_id=source_id,
                kind="feed_id",
                value="article-123",
                normalized_value="article-123",
            )
        )

    # Same GUID in the same source must fail.
    with pytest.raises(IntegrityError) as exc_info:
        db_tx.execute(
            insert(ArticleIdentifier).values(
                id=uuid4(),
                article_id=article_b,
                source_id=source_a,
                kind="feed_id",
                value="article-123",
                normalized_value="article-123",
            )
        )

    assert (
        exc_info.value.orig.diag.constraint_name
        == "uq_article_identifier"
    )


def test_article_identifier_source_integrity(db_tx):
    source_a = _create_test_source(db_tx)
    source_b = _create_test_source(db_tx)

    _, article_id = _create_test_article(db_tx, source_a)

    # An identifier cannot claim another source.
    with pytest.raises(IntegrityError) as exc_info:
        db_tx.execute(
            insert(ArticleIdentifier).values(
                id=uuid4(),
                article_id=article_id,
                source_id=source_b,
                kind="feed_id",
                value="article-456",
                normalized_value="article-456",
            )
        )

    assert (
        exc_info.value.orig.diag.constraint_name
        == "fk_article_identifier_article_source"
    )


def test_article_identifier_invalid_kind(db_tx):
    source_id, article_id = _create_test_article(db_tx)

    with pytest.raises(IntegrityError) as exc_info:
        db_tx.execute(
            insert(ArticleIdentifier).values(
                id=uuid4(),
                article_id=article_id,
                source_id=source_id,
                kind="unknown",
                value="article-123",
                normalized_value="article-123",
            )
        )

    assert (
        exc_info.value.orig.diag.constraint_name
        == "ck_article_identifier_kind"
    )


# ---------------------------------------------------------
# Category
# ---------------------------------------------------------


def test_category_null_scheme_uniqueness(db_tx):
    db_tx.execute(
        insert(Category).values(
            id=uuid4(),
            term="Python",
            scheme=None,
            label="Python Programming",
        )
    )

    with pytest.raises(IntegrityError) as exc_info:
        db_tx.execute(
            insert(Category).values(
                id=uuid4(),
                term="Python",
                scheme=None,
                label="Different Label",
            )
        )

    assert (
        exc_info.value.orig.diag.constraint_name
        == "uq_categories_scheme_term"
    )


def test_category_scheme_uniqueness(db_tx):
    # Same term with different schemes is valid.
    for scheme in ("urn:topics:a", "urn:topics:b"):
        db_tx.execute(
            insert(Category).values(
                id=uuid4(),
                term="Security",
                scheme=scheme,
            )
        )

    # Same term and scheme must fail.
    with pytest.raises(IntegrityError) as exc_info:
        db_tx.execute(
            insert(Category).values(
                id=uuid4(),
                term="Security",
                scheme="urn:topics:a",
            )
        )

    assert (
        exc_info.value.orig.diag.constraint_name
        == "uq_categories_scheme_term"
    )


def test_article_category_duplicate_link(db_tx):
    _, article_id = _create_test_article(db_tx)
    category_id = uuid4()

    db_tx.execute(
        insert(Category).values(
            id=category_id,
            term="Development",
        )
    )

    db_tx.execute(
        insert(ArticleCategory).values(
            article_id=article_id,
            category_id=category_id,
        )
    )

    with pytest.raises(IntegrityError) as exc_info:
        db_tx.execute(
            insert(ArticleCategory).values(
                article_id=article_id,
                category_id=category_id,
            )
        )

    assert (
        exc_info.value.orig.diag.constraint_name
        == "article_categories_pkey"
    )


# ---------------------------------------------------------
# Shared authors and categories
# ---------------------------------------------------------


def test_shared_author_and_category_across_sources(db_tx):
    _, article_a = _create_test_article(db_tx)
    _, article_b = _create_test_article(db_tx)

    author_id = uuid4()
    category_id = uuid4()

    db_tx.execute(
        insert(Author).values(
            id=author_id,
            name="Peter Jensen",
        )
    )

    db_tx.execute(
        insert(Category).values(
            id=category_id,
            term="Python",
        )
    )

    for article_id in (article_a, article_b):
        db_tx.execute(
            insert(ArticleAuthor).values(
                article_id=article_id,
                author_id=author_id,
                position=0,
            )
        )

        db_tx.execute(
            insert(ArticleCategory).values(
                article_id=article_id,
                category_id=category_id,
            )
        )

    author_count = db_tx.scalar(
        select(func.count())
        .select_from(ArticleAuthor)
        .where(ArticleAuthor.author_id == author_id)
    )

    category_count = db_tx.scalar(
        select(func.count())
        .select_from(ArticleCategory)
        .where(ArticleCategory.category_id == category_id)
    )

    assert author_count == 2
    assert category_count == 2


# ---------------------------------------------------------
# ArticleAuthor
# ---------------------------------------------------------


def test_article_author_position_uniqueness(db_tx):
    _, article_id = _create_test_article(db_tx)

    author_a = uuid4()
    author_b = uuid4()

    for author_id in (author_a, author_b):
        db_tx.execute(
            insert(Author).values(
                id=author_id,
                name=f"Author {author_id}",
            )
        )

    db_tx.execute(
        insert(ArticleAuthor).values(
            article_id=article_id,
            author_id=author_a,
            position=0,
        )
    )

    with pytest.raises(IntegrityError) as exc_info:
        db_tx.execute(
            insert(ArticleAuthor).values(
                article_id=article_id,
                author_id=author_b,
                position=0,
            )
        )

    assert (
        exc_info.value.orig.diag.constraint_name
        == "uq_article_author_position"
    )


def test_article_author_negative_position(db_tx):
    _, article_id = _create_test_article(db_tx)
    author_id = uuid4()

    db_tx.execute(
        insert(Author).values(
            id=author_id,
            name="Test Author",
        )
    )

    with pytest.raises(IntegrityError) as exc_info:
        db_tx.execute(
            insert(ArticleAuthor).values(
                article_id=article_id,
                author_id=author_id,
                position=-1,
            )
        )

    assert (
        exc_info.value.orig.diag.constraint_name
        == "ck_article_author_position"
    )


# ---------------------------------------------------------
# ArticleSnapshot
# ---------------------------------------------------------


def test_article_snapshot_uniqueness(db_tx):
    _, article_id = _create_test_article(db_tx)
    change_id = uuid4()

    db_tx.execute(
        insert(ArticleChange).values(
            id=change_id,
            article_id=article_id,
            change_type="content_updated",
            changes={"fields": ["title"]},
        )
    )

    db_tx.execute(
        insert(ArticleSnapshot).values(
            id=uuid4(),
            change_id=change_id,
            raw_entry={"title": "Original"},
        )
    )

    with pytest.raises(IntegrityError) as exc_info:
        db_tx.execute(
            insert(ArticleSnapshot).values(
                id=uuid4(),
                change_id=change_id,
                raw_entry={"title": "Duplicate"},
            )
        )

    assert (
        exc_info.value.orig.diag.constraint_name
        == "uq_article_snapshot_change"
    )
