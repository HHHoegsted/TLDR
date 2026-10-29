
import hashlib
import json
from calendar import timegm
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit, urlunsplit


class NormalizationError(ValueError):
    """An entry cannot safely be normalized."""


@dataclass(frozen=True, slots=True)
class NormalizedIdentifier:
    kind: Literal["feed_id", "url"]
    value: str
    normalized_value: str


@dataclass(frozen=True, slots=True)
class NormalizedAuthor:
    name: str
    uri: str | None


@dataclass(frozen=True, slots=True)
class NormalizedCategory:
    term: str
    scheme: str | None
    label: str | None


@dataclass(frozen=True, slots=True)
class NormalizedArticle:
    identifiers: tuple[NormalizedIdentifier, ...]
    url: str | None
    title: str | None
    language: str | None
    summary: str | None
    content_html: str | None
    content_text: str | None
    content_type: str | None
    published_at: datetime | None
    feed_updated_at: datetime | None
    authors: tuple[NormalizedAuthor, ...]
    categories: tuple[NormalizedCategory, ...]
    raw_entry: dict[str, Any]
    content_hash: str
    raw_hash: str


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    return value.strip() or None


def normalize_url(value: str) -> str:
    """Canonicalize HTTP(S) URLs without losing query parameters."""
    try:
        url = urlsplit(value.strip())

        scheme = url.scheme.lower()
        host = url.hostname
        port = url.port

        if (
            scheme not in {"http", "https"}
            or not host
            or url.username
            or url.password
        ):
            raise ValueError(
                "Expected an absolute HTTP(S) URL without credentials"
            )

    except ValueError as exc:
        raise NormalizationError(
            f"Invalid article URL: {value!r}"
        ) from exc

    hostname = host.lower()

    if ":" in hostname:
        hostname = f"[{hostname}]"

    default_port = (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    )

    netloc = (
        hostname
        if port is None or default_port
        else f"{hostname}:{port}"
    )

    return urlunsplit(
        (scheme, netloc, url.path or "/", url.query, "")
    )


def _utc_date(value: object) -> datetime | None:
    if value is None:
        return None

    try:
        return datetime.fromtimestamp(
            timegm(value),
            tz=timezone.utc,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise NormalizationError(
            "Invalid feedparser date tuple"
        ) from exc


def _jsonable(value: Any) -> Any:
    """Convert feedparser data to JSONB-compatible values."""
    if value is None or isinstance(
        value, (bool, str, int, float)
    ):
        return value

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise NormalizationError(
                "Raw entry contains a non-string key"
            )

        return {
            key: _jsonable(item)
            for key, item in value.items()
        }

    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]

    raise NormalizationError(
        f"Unsupported value in raw entry: {type(value).__name__}"
    )


def _digest(value: Any) -> str:
    try:
        canonical = json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise NormalizationError(
            "Entry cannot be encoded as JSON"
        ) from exc

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def _authors(
    entry: Mapping[str, Any],
) -> tuple[NormalizedAuthor, ...]:
    raw = entry.get("authors") or ()

    if not raw:
        detail = entry.get("author_detail")

        raw = (
            (detail,)
            if isinstance(detail, Mapping)
            else ({"name": entry.get("author")},)
        )

    result: list[NormalizedAuthor] = []

    for item in raw:
        if not isinstance(item, Mapping):
            continue

        name = _text(item.get("name"))

        if name:
            author = NormalizedAuthor(
                name=name,
                uri=_text(
                    item.get("href") or item.get("uri")
                ),
            )

            if author not in result:
                result.append(author)

    return tuple(result)


def _categories(
    entry: Mapping[str, Any],
) -> tuple[NormalizedCategory, ...]:
    result: list[NormalizedCategory] = []
    seen: set[tuple[str | None, str]] = set()

    for item in entry.get("tags") or ():
        if not isinstance(item, Mapping):
            continue

        term = _text(item.get("term"))

        if not term:
            continue

        category = NormalizedCategory(
            term=term,
            scheme=_text(item.get("scheme")),
            label=_text(item.get("label")),
        )

        key = (category.scheme, category.term)

        if key not in seen:
            result.append(category)
            seen.add(key)

    return tuple(result)


def _content(
    entry: Mapping[str, Any],
) -> tuple[str | None, str | None, str | None]:
    for item in entry.get("content") or ():
        if not isinstance(item, Mapping):
            continue

        value = _text(item.get("value"))

        if value is None:
            continue

        mime = _text(item.get("type")) or "text/plain"

        if mime in (
            "text/html",
            "application/xhtml+xml",
        ):
            return value, None, mime

        if mime.startswith("text/"):
            return None, value, mime

    return None, None, None


def normalize_entry(
    entry: Mapping[str, Any],
    *,
    feed_language: str | None = None,
) -> NormalizedArticle:
    """Normalize one feedparser entry without database access."""
    raw_id = _text(entry.get("id"))
    raw_url = _text(entry.get("link"))

    # feedparser may expose an opaque GUID or Atom ID
    # as the entry's link when no usable URL exists.
    # In that case, retain the identifier but not the URL.
    if (
        raw_url
        and raw_url == raw_id
        and not raw_url.lower().startswith(
            ("http://", "https://")
        )
    ):
        raw_url = None

    url = normalize_url(raw_url) if raw_url else None

    if not raw_id and not url:
        raise NormalizationError(
            "Entry has neither a feed ID nor an article URL"
        )

    if raw_id:
        id_scheme = urlsplit(raw_id).scheme.lower()

        normalized_id = (
            normalize_url(raw_id)
            if id_scheme in ("http", "https")
            else raw_id
        )

        feed_id = NormalizedIdentifier(
            "feed_id",
            raw_id,
            normalized_id,
        )
    else:
        generated = (
            "url-sha256:"
            + hashlib.sha256(
                url.encode("utf-8")
            ).hexdigest()
        )

        feed_id = NormalizedIdentifier(
            "feed_id",
            generated,
            generated,
        )

    identifiers = [feed_id]

    if url is not None:
        identifiers.append(
            NormalizedIdentifier(
                "url",
                raw_url,
                url,
            )
        )

    content_html, content_text, content_type = (
        _content(entry)
    )

    authors = _authors(entry)
    categories = _categories(entry)

    published_at = _utc_date(
        entry.get("published_parsed")
    )

    # Avoid feedparser's deprecated fallback from
    # updated_parsed to published_parsed.
    updated_value = (
        entry["updated_parsed"]
        if "updated_parsed" in entry
        else None
    )

    feed_updated_at = _utc_date(updated_value)

    raw_entry = _jsonable(entry)
    raw_hash = _digest(raw_entry)

    title = _text(entry.get("title"))

    language = (
        _text(entry.get("language"))
        or _text(feed_language)
    )

    summary = _text(entry.get("summary"))

    content_hash = _digest(
        {
            "url": url,
            "title": title,
            "language": language,
            "summary": summary,
            "content_html": content_html,
            "content_text": content_text,
            "content_type": content_type,
            "published_at": (
                published_at.isoformat()
                if published_at else None
            ),
            "feed_updated_at": (
                feed_updated_at.isoformat()
                if feed_updated_at else None
            ),
            "authors": [
                {"name": a.name, "uri": a.uri}
                for a in authors
            ],
            "categories": [
                {
                    "term": c.term,
                    "scheme": c.scheme,
                    "label": c.label,
                }
                for c in categories
            ],
        }
    )

    return NormalizedArticle(
        identifiers=tuple(identifiers),
        url=url,
        title=title,
        language=language,
        summary=summary,
        content_html=content_html,
        content_text=content_text,
        content_type=content_type,
        published_at=published_at,
        feed_updated_at=feed_updated_at,
        authors=authors,
        categories=categories,
        raw_entry=raw_entry,
        content_hash=content_hash,
        raw_hash=raw_hash,
    )
