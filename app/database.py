"""Bounded PostgreSQL connectivity checks using standard PG environment variables."""

import psycopg


def check_database() -> None:
    """Raise a psycopg error when PostgreSQL cannot serve a bounded query."""
    with psycopg.connect(connect_timeout=3, options="-c statement_timeout=2000") as connection:
        connection.execute("SELECT 1").fetchone()
