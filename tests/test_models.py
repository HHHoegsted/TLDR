
import pytest
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
    inspect,
)
from sqlalchemy.dialects.postgresql import JSONB

from models.article import Article
from models.article_change import ArticleChange
from models.article_identifier import ArticleIdentifier
from models.article_snapshot import ArticleSnapshot


# ---------------------------------------------------------
# Article
# ---------------------------------------------------------


def test_article_columns():
    columns = set(inspect(Article).columns.keys())

    expected = {
        "id",
        "source_id",
        "url",
        "title",
        "language",
        "summary",
        "content_html",
        "content_text",
        "content_type",
        "published_at",
        "feed_updated_at",
        "discovered_at",
        "last_seen_at",
        "last_changed_at",
        "raw_entry",
        "content_hash",
        "raw_hash",
        "protected_at",
        "protected_by",
        "protection_reason",
    }

    assert columns == expected


@pytest.mark.parametrize(
    "column_name",
    [
        "url",
        "title",
        "language",
        "summary",
        "content_html",
        "content_text",
        "content_type",
        "published_at",
        "feed_updated_at",
        "last_changed_at",
        "raw_entry",
        "protected_at",
        "protected_by",
        "protection_reason",
    ],
)
def test_article_optional_fields(column_name):
    column = Article.__table__.c[column_name]

    assert column.nullable is True


def test_article_raw_entry_uses_jsonb():
    column = Article.__table__.c.raw_entry

    assert isinstance(column.type, JSONB)


def test_article_composite_unique_constraint():
    constraints = Article.__table__.constraints

    assert any(
        isinstance(c, UniqueConstraint)
        and set(c.columns.keys()) == {"id", "source_id"}
        for c in constraints
    )


# ---------------------------------------------------------
# ArticleIdentifier
# ---------------------------------------------------------


def test_identifier_columns():
    columns = set(inspect(ArticleIdentifier).columns.keys())

    expected = {
        "id",
        "article_id",
        "source_id",
        "kind",
        "value",
        "normalized_value",
        "first_seen_at",
        "last_seen_at",
    }

    assert columns == expected


def test_identifier_unique_constraint():
    constraints = ArticleIdentifier.__table__.constraints

    assert any(
        isinstance(c, UniqueConstraint)
        and set(c.columns.keys())
        == {"source_id", "kind", "normalized_value"}
        for c in constraints
    )


def test_identifier_composite_foreign_key():
    constraints = ArticleIdentifier.__table__.constraints

    expected = {
        ("article_id", "articles.id"),
        ("source_id", "articles.source_id"),
    }

    assert any(
        isinstance(c, ForeignKeyConstraint)
        and {
            (e.parent.name, e.target_fullname)
            for e in c.elements
        } == expected
        for c in constraints
    )


def test_identifier_kind_check_constraint():
    constraints = ArticleIdentifier.__table__.constraints

    assert any(
        isinstance(c, CheckConstraint)
        and c.name == "ck_article_identifier_kind"
        and "feed_id" in str(c.sqltext)
        and "url" in str(c.sqltext)
        for c in constraints
    )


# ---------------------------------------------------------
# ArticleChange
# ---------------------------------------------------------


def test_article_change_columns():
    columns = set(inspect(ArticleChange).columns.keys())

    expected = {
        "id",
        "article_id",
        "detected_at",
        "change_type",
        "changes",
        "previous_content_hash",
        "new_content_hash",
        "previous_raw_hash",
        "new_raw_hash",
    }

    assert columns == expected


def test_article_change_foreign_key():
    column = ArticleChange.__table__.c.article_id

    targets = {
        fk.target_fullname
        for fk in column.foreign_keys
    }

    assert targets == {"articles.id"}


def test_article_change_jsonb():
    column = ArticleChange.__table__.c.changes

    assert isinstance(column.type, JSONB)
    assert column.nullable is False
    assert column.default is not None


def test_article_change_required_fields():
    required = {
        "id",
        "article_id",
        "detected_at",
        "change_type",
        "changes",
    }

    for name in required:
        assert ArticleChange.__table__.c[name].nullable is False


@pytest.mark.parametrize(
    "column_name",
    [
        "previous_content_hash",
        "new_content_hash",
        "previous_raw_hash",
        "new_raw_hash",
    ],
)
def test_article_change_optional_hashes(column_name):
    column = ArticleChange.__table__.c[column_name]

    assert column.nullable is True


def test_article_change_timestamp():
    column = ArticleChange.__table__.c.detected_at

    assert column.type.timezone is True
    assert column.server_default is not None


# ---------------------------------------------------------
# ArticleSnapshot
# ---------------------------------------------------------


def test_article_snapshot_columns():
    columns = set(inspect(ArticleSnapshot).columns.keys())

    expected = {
        "id",
        "change_id",
        "captured_at",
        "raw_entry",
    }

    assert columns == expected


def test_article_snapshot_foreign_key():
    column = ArticleSnapshot.__table__.c.change_id

    targets = {
        fk.target_fullname
        for fk in column.foreign_keys
    }

    assert targets == {"article_changes.id"}


def test_article_snapshot_unique_constraint():
    constraints = ArticleSnapshot.__table__.constraints

    assert any(
        isinstance(c, UniqueConstraint)
        and set(c.columns.keys()) == {"change_id"}
        for c in constraints
    )


def test_article_snapshot_raw_entry():
    column = ArticleSnapshot.__table__.c.raw_entry

    assert isinstance(column.type, JSONB)
    assert column.nullable is False


def test_article_snapshot_required_fields():
    required = {
        "id",
        "change_id",
        "captured_at",
        "raw_entry",
    }

    for name in required:
        assert ArticleSnapshot.__table__.c[name].nullable is False


def test_article_snapshot_timestamp():
    column = ArticleSnapshot.__table__.c.captured_at

    assert column.type.timezone is True
    assert column.server_default is not None
    assert column.index is True


# ---------------------------------------------------------
# Author
# ---------------------------------------------------------


def test_author_columns():
    from models.author import Author

    columns = set(inspect(Author).columns.keys())

    assert columns == {
        "id",
        "name",
        "uri",
    }


def test_author_primary_key():
    from models.author import Author

    primary_keys = {
        column.name
        for column in inspect(Author).primary_key
    }

    assert primary_keys == {"id"}


def test_author_required_fields():
    from models.author import Author

    assert Author.__table__.c.id.nullable is False
    assert Author.__table__.c.name.nullable is False
    assert Author.__table__.c.uri.nullable is True


def test_author_has_no_source_foreign_key():
    from models.author import Author

    foreign_keys = {
        fk.target_fullname
        for column in Author.__table__.columns
        for fk in column.foreign_keys
    }

    assert foreign_keys == set()


def test_author_name_is_not_unique():
    from models.author import Author

    constraints = Author.__table__.constraints

    assert not any(
        isinstance(c, UniqueConstraint)
        and "name" in c.columns.keys()
        for c in constraints
    )

    assert Author.__table__.c.name.unique is not True


# ---------------------------------------------------------
# ArticleAuthor
# ---------------------------------------------------------


def test_article_author_columns():
    from models.article_author import ArticleAuthor

    columns = set(inspect(ArticleAuthor).columns.keys())

    assert columns == {
        "article_id",
        "author_id",
        "position",
    }


def test_article_author_composite_primary_key():
    from models.article_author import ArticleAuthor

    primary_keys = {
        column.name
        for column in inspect(ArticleAuthor).primary_key
    }

    assert primary_keys == {"article_id", "author_id"}


def test_article_author_foreign_keys():
    from models.article_author import ArticleAuthor

    foreign_keys = {
        fk.target_fullname
        for column in ArticleAuthor.__table__.columns
        for fk in column.foreign_keys
    }

    assert foreign_keys == {
        "articles.id",
        "authors.id",
    }


def test_article_author_required_fields():
    from models.article_author import ArticleAuthor

    for name in ("article_id", "author_id", "position"):
        assert ArticleAuthor.__table__.c[name].nullable is False


def test_article_author_unique_position():
    from models.article_author import ArticleAuthor

    constraints = ArticleAuthor.__table__.constraints

    assert any(
        isinstance(c, UniqueConstraint)
        and set(c.columns.keys()) == {"article_id", "position"}
        for c in constraints
    )


def test_article_author_position_check():
    from models.article_author import ArticleAuthor

    constraints = ArticleAuthor.__table__.constraints

    assert any(
        isinstance(c, CheckConstraint)
        and c.name == "ck_article_author_position"
        and "position >= 0" in str(c.sqltext)
        for c in constraints
    )


# ---------------------------------------------------------
# Category
# ---------------------------------------------------------


def test_category_columns():
    from models.category import Category

    columns = set(inspect(Category).columns.keys())

    assert columns == {
        "id",
        "term",
        "scheme",
        "label",
    }


def test_category_primary_key():
    from models.category import Category

    primary_keys = {
        column.name
        for column in inspect(Category).primary_key
    }

    assert primary_keys == {"id"}


def test_category_required_fields():
    from models.category import Category

    assert Category.__table__.c.id.nullable is False
    assert Category.__table__.c.term.nullable is False


def test_category_optional_fields():
    from models.category import Category

    assert Category.__table__.c.scheme.nullable is True
    assert Category.__table__.c.label.nullable is True


def test_category_has_no_foreign_keys():
    from models.category import Category

    foreign_keys = {
        fk.target_fullname
        for column in Category.__table__.columns
        for fk in column.foreign_keys
    }

    assert foreign_keys == set()


def test_category_has_no_source_column():
    from models.category import Category

    assert "source_id" not in Category.__table__.c


# ---------------------------------------------------------
# Category - Unique Constraints
# ---------------------------------------------------------


def test_category_scheme_term_unique():
    from models.category import Category

    constraints = Category.__table__.constraints

    assert any(
        isinstance(c, UniqueConstraint)
        and set(c.columns.keys()) == {"scheme", "term"}
        and c.name == "uq_categories_scheme_term"
        for c in constraints
    )


def test_category_nulls_not_distinct():
    from models.category import Category

    unique_constraint = next(
        c
        for c in Category.__table__.constraints
        if isinstance(c, UniqueConstraint)
        and c.name == "uq_categories_scheme_term"
    )

    assert (
        unique_constraint.dialect_options["postgresql"][
            "nulls_not_distinct"
        ]
        is True
    )


def test_category_label_not_part_of_identity():
    from models.category import Category

    constraints = [
        c
        for c in Category.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]

    assert all(
        "label" not in c.columns.keys()
        for c in constraints
    )


# ---------------------------------------------------------
# ArticleCategory
# ---------------------------------------------------------


def test_article_category_columns():
    from models.article_category import ArticleCategory

    columns = set(inspect(ArticleCategory).columns.keys())

    assert columns == {
        "article_id",
        "category_id",
    }


def test_article_category_composite_primary_key():
    from models.article_category import ArticleCategory

    primary_keys = {
        column.name
        for column in inspect(ArticleCategory).primary_key
    }

    assert primary_keys == {"article_id", "category_id"}


def test_article_category_foreign_keys():
    from models.article_category import ArticleCategory

    foreign_keys = {
        fk.target_fullname
        for column in ArticleCategory.__table__.columns
        for fk in column.foreign_keys
    }

    assert foreign_keys == {
        "articles.id",
        "categories.id",
    }


def test_article_category_required_fields():
    from models.article_category import ArticleCategory

    for name in ("article_id", "category_id"):
        assert ArticleCategory.__table__.c[name].nullable is False


# ---------------------------------------------------------
# IngestionConflict
# ---------------------------------------------------------


def test_ingestion_conflict_columns():
    from models.ingestion_conflict import IngestionConflict

    columns = set(inspect(IngestionConflict).columns.keys())

    assert columns == {
        "id",
        "source_id",
        "detected_at",
        "reason",
        "identifiers",
        "candidate_article_ids",
        "raw_entry",
        "resolved_at",
        "resolved_by",
        "resolution_note",
    }


def test_ingestion_conflict_primary_key():
    from models.ingestion_conflict import IngestionConflict

    primary_keys = {
        column.name
        for column in inspect(IngestionConflict).primary_key
    }

    assert primary_keys == {"id"}


def test_ingestion_conflict_source_foreign_key():
    from models.ingestion_conflict import IngestionConflict

    column = IngestionConflict.__table__.c.source_id

    targets = {
        fk.target_fullname
        for fk in column.foreign_keys
    }

    assert targets == {"sources.id"}
    assert column.index is True


def test_ingestion_conflict_required_fields():
    from models.ingestion_conflict import IngestionConflict

    required = {
        "id",
        "source_id",
        "detected_at",
        "reason",
        "identifiers",
        "candidate_article_ids",
    }

    for name in required:
        assert IngestionConflict.__table__.c[name].nullable is False


def test_ingestion_conflict_optional_fields():
    from models.ingestion_conflict import IngestionConflict

    optional = {
        "raw_entry",
        "resolved_at",
        "resolved_by",
        "resolution_note",
    }

    for name in optional:
        assert IngestionConflict.__table__.c[name].nullable is True


def test_ingestion_conflict_jsonb_fields():
    from models.ingestion_conflict import IngestionConflict

    for name in (
        "identifiers",
        "candidate_article_ids",
        "raw_entry",
    ):
        column = IngestionConflict.__table__.c[name]

        assert isinstance(column.type, JSONB)


def test_ingestion_conflict_timestamps():
    from models.ingestion_conflict import IngestionConflict

    detected_at = IngestionConflict.__table__.c.detected_at
    resolved_at = IngestionConflict.__table__.c.resolved_at

    assert detected_at.type.timezone is True
    assert detected_at.server_default is not None

    assert resolved_at.type.timezone is True
    assert resolved_at.nullable is True
    assert resolved_at.server_default is None



# ---------------------------------------------------------
# Article <-> ArticleIdentifier Relationships
# ---------------------------------------------------------


def test_article_identifier_relationship():
    from uuid import uuid4

    from sqlalchemy.orm import configure_mappers

    from models.article import Article
    from models.article_identifier import ArticleIdentifier
    from models.source import Source

    # Ensure the referenced Source table is registered
    assert Source.__tablename__ == "sources"

    # Configure all registered ORM mappers
    configure_mappers()

    article_relationship = inspect(Article).relationships[
        "identifiers"
    ]
    identifier_relationship = inspect(
        ArticleIdentifier
    ).relationships["article"]

    # Verify both sides of the relationship
    assert article_relationship.back_populates == "article"
    assert identifier_relationship.back_populates == "identifiers"

    # Verify the composite relationship uses both keys
    column_pairs = {
        (local.name, remote.name)
        for local, remote in article_relationship.local_remote_pairs
    }

    assert column_pairs == {
        ("id", "article_id"),
        ("source_id", "source_id"),
    }

    # Verify bidirectional synchronization without a database
    source_id = uuid4()

    article = Article(
        source_id=source_id,
        content_hash="a" * 64,
        raw_hash="b" * 64,
    )

    identifier = ArticleIdentifier(
        source_id=source_id,
        kind="feed_id",
        value="article-12345",
        normalized_value="article-12345",
    )

    article.identifiers.append(identifier)

    assert identifier in article.identifiers
    assert identifier.article is article



# ---------------------------------------------------------
# Article <-> ArticleChange Relationships
# ---------------------------------------------------------


def test_article_change_relationship():
    from uuid import uuid4

    from sqlalchemy.orm import configure_mappers

    from models.article import Article
    from models.article_change import ArticleChange

    configure_mappers()

    article_relationship = inspect(Article).relationships["changes"]
    change_relationship = inspect(ArticleChange).relationships["article"]

    # Verify bidirectional relationship configuration
    assert article_relationship.back_populates == "article"
    assert change_relationship.back_populates == "changes"

    # One article has many changes
    assert article_relationship.uselist is True
    assert change_relationship.uselist is False

    # Verify synchronization without a database
    article = Article(
        source_id=uuid4(),
        content_hash="a" * 64,
        raw_hash="b" * 64,
    )

    change = ArticleChange(
        change_type="content_updated",
        changes={"fields": ["title"]},
    )

    article.changes.append(change)

    assert change in article.changes
    assert change.article is article


def test_article_changes_ordered_by_detected_at():
    from sqlalchemy.orm import configure_mappers

    from models.article import Article
    from models.article_change import ArticleChange

    configure_mappers()

    relationship = inspect(Article).relationships["changes"]

    assert len(relationship.order_by) == 1
    assert relationship.order_by[0].compare(
        ArticleChange.__table__.c.detected_at
    )


# ---------------------------------------------------------
# ArticleChange <-> ArticleSnapshot Relationships
# ---------------------------------------------------------


def test_article_change_snapshot_relationship():
    from sqlalchemy.orm import configure_mappers

    from models.article_change import ArticleChange
    from models.article_snapshot import ArticleSnapshot

    configure_mappers()

    change_relationship = inspect(ArticleChange).relationships["snapshot"]
    snapshot_relationship = inspect(ArticleSnapshot).relationships["change"]

    # Verify bidirectional relationship
    assert change_relationship.back_populates == "change"
    assert snapshot_relationship.back_populates == "snapshot"

    # Verify one-to-one cardinality
    assert change_relationship.uselist is False
    assert snapshot_relationship.uselist is False

    # Verify synchronization without a database
    change = ArticleChange(
        change_type="content_updated",
        changes={"fields": ["title"]},
    )

    snapshot = ArticleSnapshot(
        raw_entry={"title": "Previous title"},
    )

    change.snapshot = snapshot

    assert change.snapshot is snapshot
    assert snapshot.change is change


def test_article_snapshot_optional_without_delete_cascade():
    from models.article_change import ArticleChange

    change = ArticleChange(
        change_type="identifier_added",
        changes={"kind": "feed_id"},
    )

    # Not every change requires a snapshot
    assert change.snapshot is None

    # Deleting a change must not cascade-delete snapshots
    relationship = inspect(ArticleChange).relationships["snapshot"]

    assert "delete" not in relationship.cascade
    assert "delete-orphan" not in relationship.cascade


# ---------------------------------------------------------
# Article <-> ArticleAuthor <-> Author Relationships
# ---------------------------------------------------------


def test_article_author_bidirectional_relationships():
    from uuid import uuid4

    from sqlalchemy.orm import configure_mappers

    from models import Article, ArticleAuthor, Author

    configure_mappers()

    article = Article(
        source_id=uuid4(),
        content_hash="a" * 64,
        raw_hash="b" * 64,
    )

    author = Author(name="Peter Jensen")

    link = ArticleAuthor(position=0)

    article.author_links.append(link)
    author.author_links.append(link)

    assert link.article is article
    assert link.author is author
    assert link in article.author_links
    assert link in author.author_links


def test_author_can_write_for_multiple_sources():
    from uuid import uuid4

    from models import Article, ArticleAuthor, Author

    author = Author(name="Peter Jensen")

    article_one = Article(
        source_id=uuid4(),
        content_hash="a" * 64,
        raw_hash="b" * 64,
    )

    article_two = Article(
        source_id=uuid4(),
        content_hash="c" * 64,
        raw_hash="d" * 64,
    )

    link_one = ArticleAuthor(
        article=article_one,
        author=author,
        position=0,
    )

    link_two = ArticleAuthor(
        article=article_two,
        author=author,
        position=0,
    )

    assert len(author.author_links) == 2
    assert link_one.article.source_id != link_two.article.source_id
    assert link_one.author is link_two.author


def test_article_author_relationship_ordering():
    from sqlalchemy import inspect
    from sqlalchemy.orm import configure_mappers

    from models import Article, ArticleAuthor

    configure_mappers()

    relationship = inspect(Article).relationships["author_links"]

    assert relationship.uselist is True
    assert relationship.back_populates == "article"

    assert len(relationship.order_by) == 1
    assert relationship.order_by[0].compare(
        ArticleAuthor.__table__.c.position
    )


def test_author_relationship_configuration():
    from sqlalchemy import inspect
    from sqlalchemy.orm import configure_mappers

    from models import ArticleAuthor, Author

    configure_mappers()

    author_relationship = inspect(Author).relationships["author_links"]
    link_relationship = inspect(ArticleAuthor).relationships["author"]

    assert author_relationship.uselist is True
    assert link_relationship.uselist is False

    assert author_relationship.back_populates == "author"
    assert link_relationship.back_populates == "author_links"


# ---------------------------------------------------------
# Article <-> ArticleCategory <-> Category Relationships
# ---------------------------------------------------------


def test_article_category_bidirectional_relationships():
    from uuid import uuid4

    from sqlalchemy.orm import configure_mappers

    from models import Article, ArticleCategory, Category

    configure_mappers()

    article = Article(
        source_id=uuid4(),
        content_hash="a" * 64,
        raw_hash="b" * 64,
    )

    category = Category(term="Python")

    link = ArticleCategory(
        article=article,
        category=category,
    )

    assert link.article is article
    assert link.category is category
    assert link in article.category_links
    assert link in category.article_links


def test_category_can_be_shared_across_sources():
    from uuid import uuid4

    from models import Article, ArticleCategory, Category

    category = Category(term="Python")

    article_one = Article(
        source_id=uuid4(),
        content_hash="a" * 64,
        raw_hash="b" * 64,
    )

    article_two = Article(
        source_id=uuid4(),
        content_hash="c" * 64,
        raw_hash="d" * 64,
    )

    link_one = ArticleCategory(
        article=article_one,
        category=category,
    )

    link_two = ArticleCategory(
        article=article_two,
        category=category,
    )

    assert article_one.source_id != article_two.source_id
    assert len(category.article_links) == 2
    assert link_one.category is link_two.category
    assert link_one in article_one.category_links
    assert link_two in article_two.category_links


def test_article_category_relationship_configuration():
    from sqlalchemy import inspect
    from sqlalchemy.orm import configure_mappers

    from models import Article, ArticleCategory, Category

    configure_mappers()

    article_rel = inspect(Article).relationships["category_links"]
    category_rel = inspect(Category).relationships["article_links"]

    link_article_rel = inspect(ArticleCategory).relationships["article"]
    link_category_rel = inspect(ArticleCategory).relationships["category"]

    assert article_rel.uselist is True
    assert category_rel.uselist is True

    assert link_article_rel.uselist is False
    assert link_category_rel.uselist is False

    assert article_rel.back_populates == "article"
    assert link_article_rel.back_populates == "category_links"

    assert category_rel.back_populates == "category"
    assert link_category_rel.back_populates == "article_links"


def test_article_category_no_delete_cascade():
    from sqlalchemy import inspect

    from models import Article, Category

    article_rel = inspect(Article).relationships["category_links"]
    category_rel = inspect(Category).relationships["article_links"]

    for relationship in (article_rel, category_rel):
        assert "delete" not in relationship.cascade
        assert "delete-orphan" not in relationship.cascade

