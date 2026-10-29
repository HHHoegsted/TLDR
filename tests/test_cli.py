
import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from ingestion.cli import main
from models import Article, ArticleChange, Base, Source


RSS = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>TLDR Test</title>
    <description>Test feed</description>
    <item>
      <guid isPermaLink="false">test-article-123</guid>
      <title>Python news</title>
      <link>https://example.test/article-123</link>
    </item>
  </channel>
</rss>
"""


@pytest.fixture
def db_factory():
    """Create an isolated PostgreSQL schema for each CLI test.

    All schema objects and test data are created inside
    an outer transaction and disappear on rollback.

    The real TLDR tables and articles remain untouched.
    """
    url = os.getenv("DATABASE_URL")

    if not url:
        pytest.skip("DATABASE_URL is not configured")

    engine = create_engine(url)

    try:
        with engine.connect() as connection:
            transaction = connection.begin()

            try:
                schema_name = f"tldr_test_{uuid4().hex}"

                connection.exec_driver_sql(
                    f'CREATE SCHEMA "{schema_name}"'
                )

                connection.exec_driver_sql(
                    f'SET LOCAL search_path TO "{schema_name}"'
                )

                # Create the application schema in the
                # temporary PostgreSQL namespace.
                Base.metadata.create_all(connection)

                yield sessionmaker(
                    bind=connection,
                    join_transaction_mode="create_savepoint",
                )

            finally:
                transaction.rollback()

    finally:
        engine.dispose()


def _add_source(factory, name, path, *, enabled=True):
    source_id = uuid4()

    with factory() as session:
        session.add(
            Source(
                id=source_id,
                name=name,
                feed_url=f"https://example.test/{path}",
                enabled=enabled,
            )
        )
        session.commit()

    return source_id


def _count(factory, model):
    with factory() as session:
        return session.scalar(
            select(func.count()).select_from(model)
        )


def _client(handler):
    return httpx.Client(
        transport=httpx.MockTransport(handler)
    )


def _ok_response(*, etag=None):
    headers = {"Content-Type": "application/rss+xml"}

    if etag is not None:
        headers["ETag"] = etag

    return httpx.Response(
        200,
        content=RSS,
        headers=headers,
    )


def test_add_and_list_sources(db_factory, capsys):
    code = main(
        [
            "add",
            "TLDR Test",
            "HTTPS://Example.TEST:443/news.xml",
        ],
        session_factory=db_factory,
    )

    assert code == 0
    assert _count(db_factory, Source) == 1

    code = main(
        ["list"],
        session_factory=db_factory,
    )

    output = capsys.readouterr().out

    assert code == 0
    assert "TLDR Test" in output
    assert "enabled" in output
    assert "https://example.test/news.xml" in output


@pytest.mark.parametrize(
    ("name", "url"),
    [
        ("   ", "https://example.test/news.xml"),
        ("Test", "ftp://example.test/news.xml"),
    ],
)
def test_add_rejects_invalid_configuration(
    db_factory,
    capsys,
    name,
    url,
):
    code = main(
        ["add", name, url],
        session_factory=db_factory,
    )

    assert code == 2
    assert "Configuration error" in capsys.readouterr().err
    assert _count(db_factory, Source) == 0


def test_run_all_skips_disabled_sources(db_factory):
    active_id = _add_source(
        db_factory, "Active", "active.rss"
    )
    disabled_id = _add_source(
        db_factory,
        "Disabled",
        "disabled.rss",
        enabled=False,
    )

    requests = []

    def handler(request):
        requests.append(request.url.path)
        return _ok_response()

    with _client(handler) as client:
        code = main(
            ["run"],
            session_factory=db_factory,
            client=client,
        )

    assert code == 0
    assert requests == ["/active.rss"]
    assert _count(db_factory, Article) == 1

    with db_factory() as session:
        active = session.get(Source, active_id)
        disabled = session.get(Source, disabled_id)

        assert active.last_success_at is not None
        assert disabled.last_checked_at is None


def test_run_only_selected_source(db_factory):
    selected_id = _add_source(
        db_factory, "Selected", "selected.rss"
    )
    other_id = _add_source(
        db_factory, "Other", "other.rss"
    )

    with _client(
        lambda request: _ok_response()
    ) as client:
        code = main(
            ["run", "--source", str(selected_id)],
            session_factory=db_factory,
            client=client,
        )

    assert code == 0
    assert _count(db_factory, Article) == 1

    with db_factory() as session:
        article = session.scalar(select(Article))
        other = session.get(Source, other_id)

        assert article.source_id == selected_id
        assert other.last_checked_at is None


def test_failed_source_does_not_block_others(db_factory):
    bad_id = _add_source(
        db_factory, "Bad", "bad.rss"
    )
    good_id = _add_source(
        db_factory, "Good", "good.rss"
    )

    def handler(request):
        if request.url.path == "/bad.rss":
            return httpx.Response(503)

        return _ok_response()

    with _client(handler) as client:
        code = main(
            ["run"],
            session_factory=db_factory,
            client=client,
        )

    assert code == 1
    assert _count(db_factory, Article) == 1

    with db_factory() as session:
        bad = session.get(Source, bad_id)
        good = session.get(Source, good_id)

        assert bad.last_error is not None
        assert bad.last_success_at is None
        assert good.last_success_at is not None
        assert good.last_error is None


def test_repeated_run_uses_http_cache(db_factory):
    source_id = _add_source(
        db_factory, "Cached", "cached.rss"
    )

    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1

        if calls == 1:
            return _ok_response(etag='"version-1"')

        assert (
            request.headers["if-none-match"]
            == '"version-1"'
        )

        return httpx.Response(304)

    with _client(handler) as client:
        first_code = main(
            ["run", "--source", str(source_id)],
            session_factory=db_factory,
            client=client,
        )

        second_code = main(
            ["run", "--source", str(source_id)],
            session_factory=db_factory,
            client=client,
        )

    assert first_code == 0
    assert second_code == 0
    assert calls == 2
    assert _count(db_factory, Article) == 1
    assert _count(db_factory, ArticleChange) == 1

    with db_factory() as session:
        source = session.get(Source, source_id)

        assert source.etag == '"version-1"'
        assert source.last_error is None


def test_run_without_sources(db_factory, capsys):
    with _client(
        lambda request: pytest.fail(
            "No HTTP requests expected"
        )
    ) as client:
        code = main(
            ["run"],
            session_factory=db_factory,
            client=client,
        )

    assert code == 0
    assert "No enabled sources" in capsys.readouterr().out


def test_unknown_source_returns_configuration_error(
    db_factory,
    capsys,
):
    with _client(
        lambda request: pytest.fail(
            "No HTTP requests expected"
        )
    ) as client:
        code = main(
            ["run", "--source", str(uuid4())],
            session_factory=db_factory,
            client=client,
        )

    assert code == 2
    assert "Source does not exist" in capsys.readouterr().err
