
import json
import time
from datetime import datetime, timezone

import feedparser
import pytest

from ingestion.normalize import (
    NormalizationError,
    normalize_entry,
    normalize_url,
)


def test_guid_and_url_are_separate_identifiers():
    article = normalize_entry({
        "id": " urn:example:123 ",
        "link": "HTTPS://Example.COM:443/posts/123#comments",
        "title": " Test article ",
    })

    assert [
        (i.kind, i.normalized_value)
        for i in article.identifiers
    ] == [
        ("feed_id", "urn:example:123"),
        ("url", "https://example.com/posts/123"),
    ]

    assert article.title == "Test article"
    assert article.url == "https://example.com/posts/123"


def test_missing_guid_generates_stable_url_based_identifier():
    first = normalize_entry({
        "link": "https://EXAMPLE.com:443/p?x=1#top"
    })

    second = normalize_entry({
        "link": "https://example.com/p?x=1#bottom"
    })

    assert first.identifiers[0].kind == "feed_id"
    assert first.identifiers[0].value.startswith(
        "url-sha256:"
    )

    assert (
        first.identifiers[0].normalized_value
        == second.identifiers[0].normalized_value
    )

    assert (
        first.identifiers[1].normalized_value
        == second.identifiers[1].normalized_value
    )


def test_guid_without_url_is_accepted():
    article = normalize_entry({
        "id": "urn:my-feed:entry:9"
    })

    assert article.url is None
    assert len(article.identifiers) == 1


def test_entry_without_identity_is_rejected():
    with pytest.raises(
        NormalizationError,
        match="neither",
    ):
        normalize_entry({
            "title": "No GUID, no URL"
        })


def test_url_preserves_query_and_path_case():
    assert normalize_url(
        "HTTP://Example.COM:80/Path?Token=AbC#fragment"
    ) == "http://example.com/Path?Token=AbC"

    assert normalize_url(
        "https://example.com"
    ) == "https://example.com/"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/a",
        "https:///missing-host",
        "https://user:pw@example.com/a",
    ],
)
def test_invalid_article_urls_are_rejected(url):
    with pytest.raises(
        NormalizationError,
        match="Invalid article URL",
    ):
        normalize_entry({
            "id": "urn:example:1",
            "link": url,
        })


def test_authors_keep_order_and_remove_exact_duplicates():
    article = normalize_entry({
        "id": "urn:a",
        "authors": [
            {
                "name": "Ada",
                "href": "https://example.org/ada",
            },
            {
                "name": "Grace",
                "href": "https://example.org/grace",
            },
            {
                "name": "Ada",
                "href": "https://example.org/ada",
            },
        ],
    })

    assert [
        author.name for author in article.authors
    ] == ["Ada", "Grace"]

    assert (
        article.authors[0].uri
        == "https://example.org/ada"
    )


def test_author_fallback():
    article = normalize_entry({
        "id": "urn:a",
        "author": "Jane Doe",
    })

    assert [
        (author.name, author.uri)
        for author in article.authors
    ] == [("Jane Doe", None)]


def test_category_deduplication_uses_scheme_and_term():
    article = normalize_entry({
        "id": "urn:a",
        "tags": [
            {
                "term": "Python",
                "label": "Programming",
            },
            {
                "term": " Python ",
                "label": "Duplicate",
            },
            {
                "term": "Python",
                "scheme": "urn:another",
            },
        ],
    })

    assert [
        (c.term, c.scheme)
        for c in article.categories
    ] == [
        ("Python", None),
        ("Python", "urn:another"),
    ]

    assert article.categories[0].label == "Programming"


def test_content_html_and_text():
    html = normalize_entry({
        "id": "urn:a",
        "content": [
            {
                "type": "text/html",
                "value": "<p>Hello</p>",
            }
        ],
    })

    plain = normalize_entry({
        "id": "urn:b",
        "content": [
            {
                "type": "text/plain",
                "value": "Hello",
            }
        ],
    })

    assert (
        html.content_html,
        html.content_text,
        html.content_type,
    ) == ("<p>Hello</p>", None, "text/html")

    assert (
        plain.content_html,
        plain.content_text,
        plain.content_type,
    ) == (None, "Hello", "text/plain")


def test_feed_dates_are_utc_and_raw_is_json_safe():
    parsed = time.strptime(
        "2026-10-29 10:00:00",
        "%Y-%m-%d %H:%M:%S",
    )

    article = normalize_entry({
        "id": "urn:a",
        "published_parsed": parsed,
        "nested": {"one": (1, 2)},
    })

    assert article.published_at == datetime(
        2026, 10, 29, 10, tzinfo=timezone.utc
    )

    assert (
        article.raw_entry["published_parsed"]
        == list(parsed)
    )

    assert article.raw_entry["nested"] == {
        "one": [1, 2]
    }

    json.dumps(
        article.raw_entry,
        allow_nan=False,
    )


def test_unrelated_raw_change_only_changes_raw_hash():
    original = normalize_entry({
        "id": "urn:a",
        "title": "Title",
        "extra": "one",
    })

    changed = normalize_entry({
        "id": "urn:a",
        "title": "Title",
        "extra": "two",
    })

    assert original.content_hash == changed.content_hash
    assert original.raw_hash != changed.raw_hash


def test_user_visible_change_updates_content_hash():
    original = normalize_entry({
        "id": "urn:a",
        "title": "Old",
    })

    changed = normalize_entry({
        "id": "urn:a",
        "title": "New",
    })

    assert original.content_hash != changed.content_hash


def test_language_fallback_and_optional_fields():
    article = normalize_entry(
        {"id": "urn:a"},
        feed_language="da-DK",
    )

    assert article.language == "da-DK"
    assert article.summary is None
    assert article.published_at is None
    assert article.authors == ()
    assert article.categories == ()


def test_non_json_value_is_rejected():
    with pytest.raises(
        NormalizationError,
        match="Unsupported",
    ):
        normalize_entry({
            "id": "urn:a",
            "unsupported": {1, 2},
        })


def test_real_rss_entry_can_be_normalized():
    rss = b"""<rss version="2.0">
      <channel>
        <title>TLDR Test</title>
        <description>Test feed</description>
        <item>
          <guid isPermaLink="false">article-123</guid>
          <title>Python News</title>
          <link>https://example.org/python</link>
          <pubDate>Thu, 29 Oct 2026 10:00:00 GMT</pubDate>
          <category>Python</category>
        </item>
      </channel>
    </rss>"""

    feed = feedparser.parse(rss)
    article = normalize_entry(feed.entries[0])

    assert article.identifiers[0].value == "article-123"
    assert article.title == "Python News"
    assert article.url == "https://example.org/python"
    assert article.published_at == datetime(
        2026, 10, 29, 10, tzinfo=timezone.utc
    )
    assert article.categories[0].term == "Python"


def test_real_atom_entry_can_be_normalized():
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom">
      <title>TLDR Test</title>
      <id>urn:feed:test</id>
      <updated>2026-10-29T10:00:00Z</updated>
      <entry>
        <id>urn:article:agent</id>
        <title>AI Agents</title>
        <updated>2026-10-29T10:00:00Z</updated>
        <link href="https://example.org/agents"/>
        <author>
          <name>Jane Doe</name>
          <uri>https://example.org/jane</uri>
        </author>
        <content type="html">&lt;p&gt;Agent news&lt;/p&gt;</content>
      </entry>
    </feed>"""

    feed = feedparser.parse(atom)
    article = normalize_entry(feed.entries[0])

    assert (
        article.identifiers[0].value
        == "urn:article:agent"
    )
    assert article.title == "AI Agents"
    assert article.feed_updated_at == datetime(
        2026, 10, 29, 10, tzinfo=timezone.utc
    )
    assert article.authors[0].name == "Jane Doe"
    assert "Agent news" in article.content_html


def test_rss_pubdate_does_not_become_update_date():
    rss = b"""<rss version="2.0">
      <channel>
        <title>Test</title>
        <description>Test feed</description>
        <item>
          <guid>rss-123</guid>
          <title>Original article</title>
          <pubDate>Thu, 29 Oct 2026 10:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>"""

    feed = feedparser.parse(rss)

    assert "updated_parsed" not in feed.entries[0]

    article = normalize_entry(feed.entries[0])

    assert article.published_at == datetime(
        2026, 10, 29, 10, tzinfo=timezone.utc
    )
    assert article.feed_updated_at is None


def test_explicit_atom_update_date_is_preserved():
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom">
      <title>Test</title>
      <id>urn:feed:test</id>
      <updated>2026-10-30T12:00:00Z</updated>
      <entry>
        <id>urn:article:123</id>
        <title>Updated article</title>
        <published>2026-10-29T10:00:00Z</published>
        <updated>2026-10-30T12:00:00Z</updated>
      </entry>
    </feed>"""

    feed = feedparser.parse(atom)
    article = normalize_entry(feed.entries[0])

    assert article.published_at == datetime(
        2026, 10, 29, 10, tzinfo=timezone.utc
    )
    assert article.feed_updated_at == datetime(
        2026, 10, 30, 12, tzinfo=timezone.utc
    )


def test_normalization_does_not_trigger_date_fallback_warning():
    import warnings

    rss = b"""<rss version="2.0">
      <channel>
        <title>Test</title>
        <description>Test feed</description>
        <item>
          <guid>rss-456</guid>
          <pubDate>Thu, 29 Oct 2026 10:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>"""

    feed = feedparser.parse(rss)

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        article = normalize_entry(feed.entries[0])

    assert article.feed_updated_at is None
