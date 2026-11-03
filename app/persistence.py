"""Atomic measurement storage, backfill cursors, and worker heartbeat."""

from datetime import datetime

from app.database import connect
from app.source import Batch


def get_cursor(series: tuple[int, str]) -> datetime | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT covered_until FROM ingestion_cursors WHERE station_id = %s AND parameter = %s",
            series,
        ).fetchone()
        return row[0] if row else None


def store_batch(series: tuple[int, str], batch: Batch, end: datetime) -> int:
    """Commit readings and coverage together; invalid or empty batches retain coverage."""
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO measurements (station_id, parameter, ts, value) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (station_id, parameter, ts) DO NOTHING",
                [(m.station_id, m.parameter, m.ts, m.value) for m in batch.measurements],
            )
            inserted = cursor.rowcount
        if batch.measurements and not batch.rejected:
            connection.execute(
                "INSERT INTO ingestion_cursors (station_id, parameter, covered_until) "
                "VALUES (%s, %s, %s) ON CONFLICT (station_id, parameter) DO UPDATE "
                "SET covered_until = GREATEST(ingestion_cursors.covered_until, "
                "EXCLUDED.covered_until)",
                (*series, end),
            )
    return inserted


def record_cycle(finished_at: datetime, success: bool) -> None:
    with connect() as connection:
        connection.execute(
            "INSERT INTO worker_state (id, finished_at, status) VALUES (1, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET finished_at = EXCLUDED.finished_at, "
            "status = EXCLUDED.status",
            (finished_at, "ok" if success else "error"),
        )
