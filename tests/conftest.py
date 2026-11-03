"""An isolated real PostgreSQL schema; public HTTP is mocked in every source test."""

import pytest

from app.database import connect
from app.migrate import migrate


@pytest.fixture(scope="session", autouse=True)
def schema():
    migrate()


@pytest.fixture(autouse=True)
def clean_database(schema):
    with connect() as connection:
        connection.execute("TRUNCATE measurements, ingestion_cursors, worker_state")
