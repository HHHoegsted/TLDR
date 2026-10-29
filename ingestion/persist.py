
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import delete, select, tuple_
from sqlalchemy.orm import Session

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
)

from .normalize import NormalizedArticle


@dataclass(frozen=True, slots=True)
class PersistenceResult:
    status: Literal[
        "created",
        "unchanged",
        "updated",
        "raw_updated",
        "conflict",
    ]
    article_id: UUID | None
    conflict_id: UUID | None = None


def _apply_article(
    article: Article,
    item: NormalizedArticle,
    *,
    retain_payload: bool,
) -> None:
    article.url = item.url
    article.title = item.title
    article.language = item.language
    article.published_at = item.published_at
    article.feed_updated_at = item.feed_updated_at

    article.summary = (
        item.summary if retain_payload else None
    )
    article.content_html = (
        item.content_html if retain_payload else None
    )
    article.content_text = (
        item.content_text if retain_payload else None
    )
    article.content_type = (
        item.content_type if retain_payload else None
    )
    article.raw_entry = (
        item.raw_entry if retain_payload else None
    )

    article.content_hash = item.content_hash
    article.raw_hash = item.raw_hash


def _sync_authors(
    session: Session,
    article_id: UUID,
    item: NormalizedArticle,
) -> None:
    session.execute(
        delete(ArticleAuthor).where(
            ArticleAuthor.article_id == article_id
        )
    )

    for position, author_data in enumerate(item.authors):
        author = None

        # A stable URI plus name can identify an author
        # across different feeds. Name alone cannot.
        if author_data.uri:
            author = session.scalar(
                select(Author)
                .where(
                    Author.uri == author_data.uri,
                    Author.name == author_data.name,
                )
                .limit(1)
            )

        if author is None:
            author = Author(
                id=uuid4(),
                name=author_data.name,
                uri=author_data.uri,
            )
            session.add(author)
            session.flush()

        session.add(
            ArticleAuthor(
                article_id=article_id,
                author_id=author.id,
                position=position,
            )
        )


def _sync_categories(
    session: Session,
    article_id: UUID,
    item: NormalizedArticle,
) -> None:
    session.execute(
        delete(ArticleCategory).where(
            ArticleCategory.article_id == article_id
        )
    )

    for category_data in item.categories:
        category = session.scalar(
            select(Category)
            .where(
                Category.scheme == category_data.scheme,
                Category.term == category_data.term,
            )
            .limit(1)
        )

        if category is None:
            category = Category(
                id=uuid4(),
                term=category_data.term,
                scheme=category_data.scheme,
                label=category_data.label,
            )
            session.add(category)
            session.flush()

        session.add(
            ArticleCategory(
                article_id=article_id,
                category_id=category.id,
            )
        )


def _sync_metadata(
    session: Session,
    article_id: UUID,
    item: NormalizedArticle,
) -> None:
    _sync_authors(session, article_id, item)
    _sync_categories(session, article_id, item)


def persist_article(
    session: Session,
    source_id: UUID,
    item: NormalizedArticle,
    *,
    now: datetime | None = None,
) -> PersistenceResult:
    """Persist one normalized article.

    The caller owns the transaction and must commit or roll back.
    This function does not commit.
    """
    timestamp = (
        datetime.now(timezone.utc)
        if now is None
        else now
    )

    if timestamp.tzinfo is None or (
        timestamp.utcoffset() is None
    ):
        raise ValueError("now must be timezone-aware")

    timestamp = timestamp.astimezone(timezone.utc)

    keys = [
        (identifier.kind, identifier.normalized_value)
        for identifier in item.identifiers
    ]

    matches = list(
        session.scalars(
            select(ArticleIdentifier).where(
                ArticleIdentifier.source_id == source_id,
                tuple_(
                    ArticleIdentifier.kind,
                    ArticleIdentifier.normalized_value,
                ).in_(keys),
            )
        )
    )

    article_ids = {
        identifier.article_id
        for identifier in matches
    }

    # Never guess which article owns conflicting identifiers.
    if len(article_ids) > 1:
        conflict_id = uuid4()

        session.add(
            IngestionConflict(
                id=conflict_id,
                source_id=source_id,
                detected_at=timestamp,
                reason="multiple_articles_match_identifiers",
                identifiers=[
                    {
                        "kind": identifier.kind,
                        "value": identifier.value,
                        "normalized_value": (
                            identifier.normalized_value
                        ),
                    }
                    for identifier in item.identifiers
                ],
                candidate_article_ids=sorted(
                    str(article_id)
                    for article_id in article_ids
                ),
                raw_entry=item.raw_entry,
            )
        )

        session.flush()

        return PersistenceResult(
            status="conflict",
            article_id=None,
            conflict_id=conflict_id,
        )

    if not article_ids:
        article_id = uuid4()

        article = Article(
            id=article_id,
            source_id=source_id,
            discovered_at=timestamp,
            last_seen_at=timestamp,
            last_changed_at=timestamp,
        )

        _apply_article(
            article,
            item,
            retain_payload=True,
        )

        session.add(article)
        session.flush()

        for identifier in item.identifiers:
            session.add(
                ArticleIdentifier(
                    id=uuid4(),
                    article_id=article_id,
                    source_id=source_id,
                    kind=identifier.kind,
                    value=identifier.value,
                    normalized_value=identifier.normalized_value,
                    first_seen_at=timestamp,
                    last_seen_at=timestamp,
                )
            )

        _sync_metadata(session, article_id, item)

        session.add(
            ArticleChange(
                id=uuid4(),
                article_id=article_id,
                detected_at=timestamp,
                change_type="created",
                changes={
                    "identifier_kinds": [
                        identifier.kind
                        for identifier in item.identifiers
                    ]
                },
                new_content_hash=item.content_hash,
                new_raw_hash=item.raw_hash,
            )
        )

        session.flush()

        return PersistenceResult(
            status="created",
            article_id=article_id,
        )

    article_id = next(iter(article_ids))

    article = session.get(Article, article_id)

    if article is None:
        raise RuntimeError(
            "Identifier references an article that does not exist"
        )

    matched_keys = {
        (identifier.kind, identifier.normalized_value)
        for identifier in matches
    }

    added_kinds = []

    for identifier in matches:
        identifier.last_seen_at = timestamp

    for identifier in item.identifiers:
        key = (
            identifier.kind,
            identifier.normalized_value,
        )

        if key not in matched_keys:
            session.add(
                ArticleIdentifier(
                    id=uuid4(),
                    article_id=article_id,
                    source_id=source_id,
                    kind=identifier.kind,
                    value=identifier.value,
                    normalized_value=identifier.normalized_value,
                    first_seen_at=timestamp,
                    last_seen_at=timestamp,
                )
            )

            added_kinds.append(identifier.kind)

    content_changed = (
        article.content_hash != item.content_hash
    )
    raw_changed = article.raw_hash != item.raw_hash

    expired = (
        article.protected_at is None
        and article.discovered_at
        <= timestamp - timedelta(days=30)
    )

    article.last_seen_at = timestamp

    if not content_changed and not raw_changed:
        if expired:
            _apply_article(
                article,
                item,
                retain_payload=False,
            )

        session.flush()

        return PersistenceResult(
            status="unchanged",
            article_id=article_id,
        )

    previous_content_hash = article.content_hash
    previous_raw_hash = article.raw_hash
    previous_raw_entry = article.raw_entry

    change_id = uuid4()

    session.add(
        ArticleChange(
            id=change_id,
            article_id=article_id,
            detected_at=timestamp,
            change_type=(
                "updated"
                if content_changed
                else "raw_updated"
            ),
            changes={
                "content_changed": content_changed,
                "raw_changed": raw_changed,
                "added_identifier_kinds": added_kinds,
            },
            previous_content_hash=previous_content_hash,
            new_content_hash=item.content_hash,
            previous_raw_hash=previous_raw_hash,
            new_raw_hash=item.raw_hash,
        )
    )

    # Do not create new historical payloads for articles
    # whose content retention period has already expired.
    if previous_raw_entry is not None and not expired:
        session.add(
            ArticleSnapshot(
                id=uuid4(),
                change_id=change_id,
                captured_at=timestamp,
                raw_entry=previous_raw_entry,
            )
        )

    _apply_article(
        article,
        item,
        retain_payload=not expired,
    )

    article.last_changed_at = timestamp

    if content_changed:
        _sync_metadata(session, article_id, item)

    session.flush()

    return PersistenceResult(
        status=(
            "updated"
            if content_changed
            else "raw_updated"
        ),
        article_id=article_id,
    )
