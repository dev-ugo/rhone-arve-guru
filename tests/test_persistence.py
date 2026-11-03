"""Verify PostgreSQL conflict handling, constraints, and atomic backfill progress."""

from datetime import UTC, datetime, timedelta, timezone

import psycopg
import pytest

from app.database import connect
from app.migrate import migrate
from app.persistence import get_cursor, store_batch
from app.source import Batch, Measurement

NOW = datetime(2026, 1, 10, 12, tzinfo=UTC)
SERIES = (2606, "flow")


def test_repeated_ingestion_and_overlapping_batches_never_duplicate_or_replace_values():
    batch = Batch([Measurement(*SERIES, NOW, 123.4)] * 2, 0)
    assert store_batch(SERIES, batch, NOW) == 1
    assert store_batch(SERIES, batch, NOW) == 0
    assert store_batch(SERIES, Batch([Measurement(*SERIES, NOW, 999)], 0), NOW) == 0
    with connect() as connection:
        assert connection.execute("SELECT count(*), min(value) FROM measurements").fetchone() == (
            1,
            123.4,
        )
        assert (
            connection.execute(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'measurements' AND column_name = 'ts'"
            ).fetchone()[0]
            == "timestamp with time zone"
        )


def test_empty_or_partially_invalid_batches_do_not_advance_cursor():
    store_batch(SERIES, Batch([Measurement(*SERIES, NOW, 123.4)], 0), NOW)
    later = NOW + timedelta(hours=1)
    store_batch(SERIES, Batch([], 0), later)
    assert get_cursor(SERIES) == NOW
    store_batch(SERIES, Batch([Measurement(*SERIES, later, 120)], 1), later)
    assert get_cursor(SERIES) == NOW
    store_batch(SERIES, Batch([Measurement(*SERIES, later, 120)], 0), later)
    assert get_cursor(SERIES) == later
    store_batch(SERIES, Batch([Measurement(*SERIES, NOW, 123.4)], 0), NOW)
    assert get_cursor(SERIES) == later


def test_constraint_failure_rolls_back_measurements_and_cursor():
    batch = Batch([Measurement(*SERIES, NOW, 123), Measurement(2606, "height", NOW, 12)], 0)
    with pytest.raises(psycopg.errors.CheckViolation):
        store_batch(SERIES, batch, NOW)
    assert get_cursor(SERIES) is None
    with connect() as connection:
        assert connection.execute("SELECT count(*) FROM measurements").fetchone()[0] == 0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_database_rejects_nonfinite_measurements(value):
    with pytest.raises(psycopg.errors.CheckViolation):
        store_batch(SERIES, Batch([Measurement(*SERIES, NOW, value)], 0), NOW)


def test_migrations_can_be_reapplied_to_existing_data_without_losing_it():
    local_time = NOW.astimezone(timezone(timedelta(hours=2)))
    store_batch(SERIES, Batch([Measurement(*SERIES, local_time, 123)], 0), NOW)
    migrate()
    migrate()
    with connect() as connection:
        assert connection.execute("SELECT ts FROM measurements").fetchone()[0] == NOW
        assert connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1
