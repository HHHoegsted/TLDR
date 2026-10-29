
import os

import pytest
from sqlalchemy.engine import make_url


def pytest_configure(config: pytest.Config) -> None:
    """Always use a separate PostgreSQL database for tests."""
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        return

    url = make_url(database_url)

    if not url.database:
        raise pytest.UsageError(
            "DATABASE_URL must specify a database"
        )

    if not url.database.endswith("_test"):
        url = url.set(database=f"{url.database}_test")

    # This only affects the pytest process.
    # The user's PowerShell environment is unchanged.
    os.environ["DATABASE_URL"] = url.render_as_string(
        hide_password=False
    )
