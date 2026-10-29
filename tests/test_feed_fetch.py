
import httpx
import pytest

from ingestion import InvalidFeedError, fetch_feed


RSS_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>TLDR Dev</title>
    <link>https://example.com/</link>
    <description>Development news</description>
    <item>
      <guid isPermaLink="false">article-123</guid>
      <title>Python 3.14 Released</title>
      <link>https://example.com/python</link>
      <pubDate>Thu, 29 Oct 2026 10:00:00 GMT</pubDate>
      <category>Python</category>
    </item>
  </channel>
</rss>
"""


ATOM_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>TLDR AI</title>
  <id>https://example.com/atom</id>
  <updated>2026-10-29T10:00:00Z</updated>
  <entry>
    <title>AI Agents</title>
    <id>urn:example:agent-123</id>
    <updated>2026-10-29T10:00:00Z</updated>
    <link href="https://example.com/agents"/>
  </entry>
</feed>
"""


def _client(handler):
    return httpx.Client(
        transport=httpx.MockTransport(handler)
    )


def test_fetch_rss_feed():
    def handler(request):
        assert request.headers["user-agent"] == "TLDR/0.1"
        assert "application/rss+xml" in request.headers["accept"]

        return httpx.Response(
            200,
            content=RSS_FEED,
            headers={"Content-Type": "application/rss+xml"},
        )

    with _client(handler) as client:
        result = fetch_feed(client, "https://example.com/rss")

    assert result.status == "updated"
    assert result.http_status == 200
    assert result.title == "TLDR Dev"
    assert result.version == "rss20"
    assert len(result.entries) == 1

    entry = result.entries[0]

    assert entry["id"] == "article-123"
    assert entry["title"] == "Python 3.14 Released"
    assert entry["link"] == "https://example.com/python"
    assert entry["tags"][0]["term"] == "Python"


def test_fetch_atom_feed():
    def handler(request):
        return httpx.Response(
            200,
            content=ATOM_FEED,
            headers={"Content-Type": "application/atom+xml"},
        )

    with _client(handler) as client:
        result = fetch_feed(client, "https://example.com/atom")

    assert result.status == "updated"
    assert result.version == "atom10"
    assert result.title == "TLDR AI"
    assert len(result.entries) == 1

    assert result.entries[0]["id"] == "urn:example:agent-123"
    assert result.entries[0]["title"] == "AI Agents"


def test_empty_feed_is_valid():
    empty_feed = b"""<rss version="2.0">
      <channel>
        <title>Empty Feed</title>
        <description>No articles</description>
      </channel>
    </rss>"""

    with _client(
        lambda request: httpx.Response(
            200,
            content=empty_feed,
        )
    ) as client:
        result = fetch_feed(client, "https://example.com/empty")

    assert result.status == "updated"
    assert result.entries == ()
    assert result.title == "Empty Feed"


def test_conditional_request_and_304():
    etag = '"version-123"'
    last_modified = "Thu, 29 Oct 2026 10:00:00 GMT"

    def handler(request):
        assert request.headers["if-none-match"] == etag
        assert request.headers["if-modified-since"] == last_modified

        return httpx.Response(304)

    with _client(handler) as client:
        result = fetch_feed(
            client,
            "https://example.com/rss",
            etag=etag,
            last_modified=last_modified,
        )

    assert result.status == "not_modified"
    assert result.http_status == 304
    assert result.entries == ()
    assert result.etag == etag
    assert result.last_modified == last_modified


def test_304_can_update_cache_validators():
    with _client(
        lambda request: httpx.Response(
            304,
            headers={
                "ETag": '"new-version"',
                "Last-Modified": "Fri, 30 Oct 2026 10:00:00 GMT",
            },
        )
    ) as client:
        result = fetch_feed(
            client,
            "https://example.com/rss",
            etag='"old-version"',
        )

    assert result.status == "not_modified"
    assert result.etag == '"new-version"'
    assert result.last_modified == "Fri, 30 Oct 2026 10:00:00 GMT"


def test_200_returns_new_cache_validators():
    with _client(
        lambda request: httpx.Response(
            200,
            content=RSS_FEED,
            headers={
                "ETag": '"new-version"',
                "Last-Modified": "Thu, 29 Oct 2026 10:00:00 GMT",
            },
        )
    ) as client:
        result = fetch_feed(
            client,
            "https://example.com/rss",
            etag='"old-version"',
        )

    assert result.etag == '"new-version"'
    assert result.last_modified == "Thu, 29 Oct 2026 10:00:00 GMT"


def test_200_clears_obsolete_cache_validators():
    with _client(
        lambda request: httpx.Response(
            200,
            content=RSS_FEED,
        )
    ) as client:
        result = fetch_feed(
            client,
            "https://example.com/rss",
            etag='"old-version"',
            last_modified="Thu, 29 Oct 2026 10:00:00 GMT",
        )

    assert result.etag is None
    assert result.last_modified is None


def test_rejects_malformed_xml():
    malformed = b"<rss><channel><item></rss>"

    with _client(
        lambda request: httpx.Response(
            200,
            content=malformed,
        )
    ) as client:
        with pytest.raises(InvalidFeedError):
            fetch_feed(client, "https://example.com/broken")


def test_rejects_html_instead_of_feed():
    html = b"<html><body>Not a feed</body></html>"

    with _client(
        lambda request: httpx.Response(
            200,
            content=html,
            headers={"Content-Type": "text/html"},
        )
    ) as client:
        with pytest.raises(InvalidFeedError):
            fetch_feed(client, "https://example.com/not-a-feed")


def test_http_error_propagates():
    with _client(
        lambda request: httpx.Response(503)
    ) as client:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            fetch_feed(client, "https://example.com/rss")

    assert exc_info.value.response.status_code == 503


def test_timeout_propagates():
    def handler(request):
        raise httpx.ReadTimeout(
            "Request timed out",
            request=request,
        )

    with _client(handler) as client:
        with pytest.raises(httpx.ReadTimeout):
            fetch_feed(client, "https://example.com/rss")


def test_follows_http_redirects():
    requested_paths = []

    def handler(request):
        requested_paths.append(request.url.path)

        if request.url.path == "/old.xml":
            return httpx.Response(
                302,
                headers={"Location": "/new.xml"},
            )

        return httpx.Response(
            200,
            content=RSS_FEED,
        )

    with _client(handler) as client:
        result = fetch_feed(
            client,
            "https://example.com/old.xml",
        )

    assert requested_paths == ["/old.xml", "/new.xml"]
    assert result.status == "updated"
    assert len(result.entries) == 1


def test_accepts_recovered_encoding_mismatch():
    # text/xml without charset defaults to US-ASCII
    # in feedparser's encoding detection.
    #
    # The document actually uses UTF-8 and includes
    # non-ASCII characters.
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <title>Nyheder om sikkerhed</title>
        <description>Danske nyheder</description>
        <item>
          <guid>news-123</guid>
          <title>Ændringer i København</title>
          <link>https://example.com/news-123</link>
        </item>
      </channel>
    </rss>
    """.encode("utf-8")

    def handler(request):
        return httpx.Response(
            200,
            content=rss,
            headers={"Content-Type": "text/xml"},
        )

    with _client(handler) as client:
        result = fetch_feed(
            client,
            "https://example.com/feed.xml",
        )

    assert result.status == "updated"
    assert result.version == "rss20"
    assert len(result.entries) == 1
    assert result.entries[0]["title"] == (
        "Ændringer i København"
    )


def test_encoding_tolerance_does_not_allow_malformed_xml():
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <title>Nyheder</title>
        <item>
          <title>Ødelagt XML</title>
        </channel>
    </rss>
    """.encode("utf-8")

    with _client(
        lambda request: httpx.Response(
            200,
            content=rss,
            headers={"Content-Type": "text/xml"},
        )
    ) as client:
        with pytest.raises(InvalidFeedError):
            fetch_feed(
                client,
                "https://example.com/broken.xml",
            )
