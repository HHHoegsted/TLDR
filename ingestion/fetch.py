
from dataclasses import dataclass
from typing import Any, Literal

import feedparser
import httpx


class InvalidFeedError(ValueError):
    """The HTTP response does not contain a valid RSS/Atom feed."""


@dataclass(frozen=True, slots=True)
class FeedFetchResult:
    status: Literal["updated", "not_modified"]
    http_status: int
    title: str | None
    version: str | None
    entries: tuple[dict[str, Any], ...]
    etag: str | None
    last_modified: str | None


def fetch_feed(
    client: httpx.Client,
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
) -> FeedFetchResult:
    """Fetch and parse a single RSS/Atom feed.

    The caller owns the HTTP client and its lifecycle.

    A 304 response returns no entries. HTTP and network errors
    propagate to the caller. Invalid feeds raise InvalidFeedError.

    A recovered character-encoding mismatch is not considered
    a fatal parsing error.
    """

    headers = {
        "Accept": (
            "application/atom+xml, application/rss+xml, "
            "application/xml, text/xml;q=0.9, */*;q=0.5"
        ),
        "User-Agent": "TLDR/0.1",
    }

    if etag:
        headers["If-None-Match"] = etag

    if last_modified:
        headers["If-Modified-Since"] = last_modified

    response = client.get(
        url,
        headers=headers,
        follow_redirects=True,
    )

    if response.status_code == 304:
        return FeedFetchResult(
            status="not_modified",
            http_status=304,
            title=None,
            version=None,
            entries=(),
            etag=response.headers.get("etag", etag),
            last_modified=response.headers.get(
                "last-modified",
                last_modified,
            ),
        )

    response.raise_for_status()

    parsed = feedparser.parse(
        response.content,
        response_headers={
            "content-type": response.headers.get(
                "content-type",
                "application/xml",
            ),
        },
    )

    # feedparser sets bozo=1 for different kinds of errors.
    #
    # CharacterEncodingOverride means that the declared
    # encoding was wrong, but feedparser successfully
    # recovered using another encoding.
    #
    # Other parsing errors remain fatal.
    if parsed.get("bozo"):
        problem = parsed.get("bozo_exception")

        if not isinstance(
            problem,
            feedparser.CharacterEncodingOverride,
        ):
            raise InvalidFeedError(
                f"Malformed feed: {problem}"
            )

    # A recovered encoding mismatch alone is not enough
    # to prove that the response contains a valid feed.
    version = parsed.get("version") or None

    if not version or not version.startswith(
        ("rss", "atom")
    ):
        raise InvalidFeedError(
            "Response is not a recognized RSS/Atom feed"
        )

    return FeedFetchResult(
        status="updated",
        http_status=response.status_code,
        title=parsed.feed.get("title") or None,
        version=version,
        entries=tuple(parsed.entries),
        etag=response.headers.get("etag"),
        last_modified=response.headers.get("last-modified"),
    )
