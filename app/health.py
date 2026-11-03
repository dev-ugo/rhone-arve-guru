"""Infrastructure, worker execution, and per-series freshness are distinct signals."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.database import connect
from app.series import FRESHNESS, SERIES, UNITS


class SeriesHealth(BaseModel):
    station_id: int
    parameter: str
    unit: str
    latest_at: datetime | None
    status: Literal["fresh", "stale", "missing"]


class IngestionHealth(BaseModel):
    worker: Literal["starting", "ok", "error", "stale", "unavailable"] = "unavailable"
    worker_finished_at: datetime | None = None
    data: Literal["fresh", "stale", "unavailable"] = "unavailable"
    series: list[SeriesHealth] = Field(default_factory=list)


def ingestion_health() -> IngestionHealth:
    now = datetime.now(UTC)
    with connect() as connection:
        worker = connection.execute(
            "SELECT finished_at, status FROM worker_state WHERE id = 1"
        ).fetchone()
        latest = {
            (row[0], row[1]): row[2]
            for row in connection.execute(
                "SELECT station_id, parameter, max(ts) FROM measurements "
                "GROUP BY station_id, parameter"
            )
        }
    series = []
    for station, parameter in SERIES:
        ts = latest.get((station, parameter))
        status = "missing" if ts is None else "fresh" if now - FRESHNESS <= ts <= now else "stale"
        series.append(
            SeriesHealth(
                station_id=station,
                parameter=parameter,
                unit=UNITS[parameter],
                latest_at=ts,
                status=status,
            )
        )
    return IngestionHealth(
        worker=(
            "starting"
            if worker is None
            else "stale"
            if not now - FRESHNESS <= worker[0] <= now
            else worker[1]
        ),
        worker_finished_at=worker[0] if worker else None,
        data=(
            "unavailable"
            if not latest
            else "fresh"
            if all(s.status == "fresh" for s in series)
            else "stale"
        ),
        series=series,
    )


def check_worker() -> bool:
    """Liveness depends on completed cycles, even when the public source is down."""
    with connect() as connection:
        row = connection.execute(
            "SELECT finished_at BETWEEN now() - interval '30 minutes' AND now() "
            "FROM worker_state WHERE id = 1"
        ).fetchone()
    return bool(row and row[0])


if __name__ == "__main__":
    raise SystemExit(0 if check_worker() else 1)
