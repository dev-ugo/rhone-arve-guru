"""Bounded PostgreSQL connections using standard PG environment variables."""

import psycopg


def connect() -> psycopg.Connection:
    return psycopg.connect(connect_timeout=3, options="-c statement_timeout=5000 -c timezone=UTC")


def check_database() -> None:
    """Raise a psycopg error when PostgreSQL cannot serve a bounded query."""
    with connect() as connection:
        connection.execute("SELECT 1").fetchone()
