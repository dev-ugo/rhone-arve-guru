"""Read-only, bounded measurement routes with explicit per-series freshness."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field

from app.database import connect
from app.series import FRESHNESS, SERIES, UNITS

router = APIRouter()
MAX_HISTORY_AGE = timedelta(days=30)
MAX_HISTORY_POINTS = 5000
WARNING = (
    "The application does not replace official guidance and cannot determine "
    "whether swimming is permitted or safe."
)
Freshness = Literal["fresh", "stale", "missing"]


class ErrorResponse(BaseModel):
    detail: str


class LatestSeries(BaseModel):
    station_id: int
    parameter: str
    unit: str
    ts: datetime | None
    value: float | None
    status: Freshness


class UnavailableIndex(BaseModel):
    status: Literal["unavailable"] = "unavailable"
    reason: Literal["data_missing", "data_stale", "calibration_pending", "unit_validation_pending"]


class Indices(BaseModel):
    current: UnavailableIndex
    jonction: UnavailableIndex


class LatestResponse(BaseModel):
    generated_at: datetime
    data: Literal["fresh", "stale", "unavailable"]
    series: list[LatestSeries]
    indices: Indices
    warning: str = WARNING


class HistoryPoint(BaseModel):
    ts: datetime
    value: float


class HistoryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    generated_at: datetime
    station_id: int
    parameter: str
    unit: str
    from_: datetime = Field(alias="from")
    to: datetime
    status: Freshness
    latest_at: datetime | None
    points: list[HistoryPoint]


def utc_now() -> datetime:
    return datetime.now(UTC)


def freshness(ts: datetime | None, now: datetime) -> Freshness:
    if ts is None:
        return "missing"
    return "fresh" if now - FRESHNESS <= ts <= now else "stale"


def index_reason(status: Freshness, pending: str) -> str:
    return {"missing": "data_missing", "stale": "data_stale"}.get(status, pending)


def require_iso_timestamp(value: object) -> object:
    """Reject Unix timestamps and date-only strings before datetime coercion."""
    if (
        not isinstance(value, str)
        or not 17 <= len(value) <= 40
        or value[4] != "-"
        or value[7] != "-"
        or value[10] not in "Tt"
    ):
        raise ValueError("Use a timezone-aware ISO 8601 timestamp")
    return value


IsoTimestamp = Annotated[AwareDatetime, BeforeValidator(require_iso_timestamp)]


@router.get("/latest", response_model=LatestResponse, responses={503: {"model": ErrorResponse}})
def latest() -> LatestResponse:
    """Return all six expected series, retaining stale readings and explicit gaps."""
    now = utc_now()
    try:
        with connect() as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            rows = connection.execute(
                "SELECT wanted.station_id, wanted.parameter, reading.ts, reading.value "
                "FROM unnest(%s::integer[], %s::text[]) WITH ORDINALITY "
                "AS wanted(station_id, parameter, position) "
                "LEFT JOIN LATERAL ("
                "SELECT ts, value FROM measurements "
                "WHERE station_id = wanted.station_id AND parameter = wanted.parameter "
                "ORDER BY ts DESC LIMIT 1"
                ") AS reading ON TRUE ORDER BY wanted.position",
                ([station for station, _ in SERIES], [parameter for _, parameter in SERIES]),
            ).fetchall()
    except psycopg.Error:
        raise HTTPException(503, "Measurements are temporarily unavailable") from None
    series = [
        LatestSeries(
            station_id=station,
            parameter=parameter,
            unit=UNITS[parameter],
            ts=ts,
            value=value,
            status=freshness(ts, now),
        )
        for station, parameter, ts, value in rows
    ]
    states = {(item.station_id, item.parameter): item.status for item in series}
    return LatestResponse(
        generated_at=now,
        data=(
            "unavailable"
            if all(item.status == "missing" for item in series)
            else "fresh"
            if all(item.status == "fresh" for item in series)
            else "stale"
        ),
        series=series,
        indices=Indices(
            current=UnavailableIndex(
                reason=index_reason(states[(2606, "flow")], "calibration_pending")
            ),
            jonction=UnavailableIndex(
                reason=index_reason(states[(2170, "turbidity")], "unit_validation_pending")
            ),
        ),
    )


@router.get(
    "/history",
    response_model=HistoryResponse,
    responses={503: {"model": ErrorResponse}},
)
def history(
    station: Annotated[int, Query(ge=1, le=9999)],
    param: Annotated[Literal["flow", "temperature", "height", "turbidity"], Query()],
    start: Annotated[
        IsoTimestamp,
        Query(alias="from", description="Timezone-aware ISO 8601 start within the last 30 days"),
    ],
) -> HistoryResponse:
    """Return at most 5000 chronological points, without interpolation or truncation."""
    now = utc_now()
    if (station, param) not in SERIES:
        raise HTTPException(422, "Unsupported station and parameter combination")
    if not now - MAX_HISTORY_AGE <= start <= now:
        raise HTTPException(422, "from must be within the last 30 days and not in the future")
    start = start.astimezone(UTC)
    try:
        with connect() as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            rows = connection.execute(
                "SELECT ts, value FROM measurements "
                "WHERE station_id = %s AND parameter = %s AND ts >= %s AND ts <= %s "
                "ORDER BY ts ASC LIMIT %s",
                (station, param, start, now, MAX_HISTORY_POINTS + 1),
            ).fetchall()
    except psycopg.Error:
        raise HTTPException(503, "Measurements are temporarily unavailable") from None
    if len(rows) > MAX_HISTORY_POINTS:
        raise HTTPException(
            422, "History exceeds 5000 points; request a more recent from timestamp"
        )
    latest_at = rows[-1][0] if rows else None
    return HistoryResponse(
        generated_at=now,
        station_id=station,
        parameter=param,
        unit=UNITS[param],
        from_=start,
        to=now,
        status=freshness(latest_at, now),
        latest_at=latest_at,
        points=[HistoryPoint(ts=ts, value=value) for ts, value in rows],
    )
