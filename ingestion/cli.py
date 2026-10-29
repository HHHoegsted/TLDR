
import argparse
import os
import sys
from collections.abc import Sequence
from uuid import UUID, uuid4

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from models import Source

from .normalize import normalize_url
from .service import IngestionResult, ingest_source


def add_source(
    session_factory: sessionmaker[Session],
    name: str,
    feed_url: str,
) -> UUID:
    """Register a source and commit it."""
    name = name.strip()

    if not name:
        raise ValueError("Source name cannot be empty")

    url = normalize_url(feed_url)
    source_id = uuid4()

    with session_factory() as session:
        session.add(
            Source(
                id=source_id,
                name=name,
                feed_url=url,
            )
        )
        session.commit()

    return source_id


def list_sources(
    session_factory: sessionmaker[Session],
) -> None:
    """Print configured sources."""
    with session_factory() as session:
        sources = list(
            session.scalars(
                select(Source).order_by(
                    Source.name,
                    Source.id,
                )
            )
        )

        if not sources:
            print("No sources configured.")
            return

        for source in sources:
            state = (
                "enabled"
                if source.enabled
                else "disabled"
            )

            print(
                f"{source.id}  "
                f"{state:8}  "
                f"{source.name}  "
                f"{source.feed_url}"
            )


def run_sources(
    session_factory: sessionmaker[Session],
    client: httpx.Client,
    *,
    source_id: UUID | None = None,
) -> list[IngestionResult]:
    """Ingest selected sources, committing each independently."""

    with session_factory() as session:
        if source_id is not None:
            if session.get(Source, source_id) is None:
                raise ValueError(
                    f"Source does not exist: {source_id}"
                )

            source_ids = [source_id]

        else:
            source_ids = list(
                session.scalars(
                    select(Source.id)
                    .where(Source.enabled.is_(True))
                    .order_by(Source.id)
                )
            )

    results: list[IngestionResult] = []

    for current_id in source_ids:
        try:
            with session_factory() as session:
                result = ingest_source(
                    session,
                    client,
                    current_id,
                )

                # Commit only after ingestion succeeds
                # or returns a handled feed failure.
                session.commit()

        except SQLAlchemyError as exc:
            # Closing the session rolls back its transaction.
            # Continue processing other sources.
            result = IngestionResult(
                source_id=current_id,
                status="failed",
                error=(
                    f"Database error: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

        results.append(result)

    return results


def _report_results(
    results: list[IngestionResult],
) -> int:
    if not results:
        print(
            "No enabled sources. "
            "Use 'python -m ingestion add' to register one."
        )
        return 0

    failed = False

    for result in results:
        print(
            f"{result.source_id}  "
            f"{result.status}  "
            f"seen={result.entries_seen}  "
            f"created={result.created}  "
            f"unchanged={result.unchanged}  "
            f"updated={result.updated}  "
            f"raw_updated={result.raw_updated}  "
            f"conflicts={result.conflicts}"
        )

        if result.error:
            print(
                f"  Error: {result.error}",
                file=sys.stderr,
            )

        if result.status == "failed":
            failed = True

    return 1 if failed else 0


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: sessionmaker[Session] | None = None,
    client: httpx.Client | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="tldr",
        description="TLDR RSS/Atom ingestion",
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    add_parser = commands.add_parser(
        "add",
        help="Register an RSS/Atom source",
    )
    add_parser.add_argument("name")
    add_parser.add_argument("feed_url")

    commands.add_parser(
        "list",
        help="List configured sources",
    )

    run_parser = commands.add_parser(
        "run",
        help="Ingest enabled sources",
    )
    run_parser.add_argument(
        "--source",
        type=UUID,
        dest="source_id",
        help="Ingest one source by UUID",
    )

    args = parser.parse_args(argv)

    engine = None

    try:
        if session_factory is None:
            database_url = os.getenv("DATABASE_URL")

            if not database_url:
                print(
                    "DATABASE_URL is not configured.",
                    file=sys.stderr,
                )
                return 2

            engine = create_engine(database_url)
            session_factory = sessionmaker(bind=engine)

        if args.command == "add":
            source_id = add_source(
                session_factory,
                args.name,
                args.feed_url,
            )

            print(f"Added source: {source_id}")
            return 0

        if args.command == "list":
            list_sources(session_factory)
            return 0

        if args.command == "run":
            if client is not None:
                results = run_sources(
                    session_factory,
                    client,
                    source_id=args.source_id,
                )

            else:
                with httpx.Client(timeout=20.0) as http_client:
                    results = run_sources(
                        session_factory,
                        http_client,
                        source_id=args.source_id,
                    )

            return _report_results(results)

    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    except SQLAlchemyError as exc:
        print(
            f"Database error: {exc}",
            file=sys.stderr,
        )
        return 1

    finally:
        if engine is not None:
            engine.dispose()

    return 2
