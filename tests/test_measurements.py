"""Exercise bounded read-only routes against an isolated real PostgreSQL database."""

import asyncio
from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest

from app import measurements
from app.database import connect
from app.main import app
from app.persistence import store_batch
from app.series import SERIES, UNITS
from app.source import Batch, Measurement

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(measurements, "utc_now", lambda: NOW)


def request(method: str, path: str, params: dict | None = None) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.request(method, path, params=params)

    return asyncio.run(send())


def history_response(**overrides) -> httpx.Response:
    params = {"station": 2606, "param": "flow", "from": (NOW - timedelta(days=1)).isoformat()}
    params.update(overrides)
    return request("GET", "/history", params)


def store(series: tuple[int, str], points: list[tuple[datetime, float]]) -> None:
    store_batch(series, Batch([Measurement(*series, ts, value) for ts, value in points], 0), NOW)


def test_latest_preserves_all_missing_series_and_unavailable_indices():
    response = request("GET", "/latest")
    assert response.status_code == 200
    body = response.json()
    assert body["generated_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert body["data"] == "unavailable"
    assert [(item["station_id"], item["parameter"]) for item in body["series"]] == list(SERIES)
    for item in body["series"]:
        assert item["unit"] == UNITS[item["parameter"]]
        assert item["ts"] is item["value"] is None
        assert item["status"] == "missing"
    assert body["indices"] == {
        "current": {"status": "unavailable", "reason": "data_missing"},
        "jonction": {"status": "unavailable", "reason": "data_missing"},
    }
    assert "does not replace official guidance" in body["warning"]


def test_latest_selects_newest_per_series_without_conflating_timestamps_or_zero():
    for index, series in enumerate(SERIES):
        store(
            series,
            [(NOW - timedelta(days=1), 999), (NOW - timedelta(minutes=index), index)],
        )
    response = request("GET", "/latest")
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == "fresh"
    for index, item in enumerate(body["series"]):
        assert item["status"] == "fresh"
        assert item["value"] == index
        assert datetime.fromisoformat(item["ts"]) == NOW - timedelta(minutes=index)
    assert body["indices"] == {
        "current": {"status": "unavailable", "reason": "calibration_pending"},
        "jonction": {"status": "unavailable", "reason": "unit_validation_pending"},
    }


def test_latest_freshness_is_per_series_inclusive_and_future_dates_are_stale():
    offsets = [
        timedelta(minutes=-30),
        -timedelta(minutes=30, microseconds=1),
        timedelta(microseconds=1),
        timedelta(),
    ]
    for series, offset in zip(SERIES, offsets, strict=False):
        store(series, [(NOW + offset, 12)])
    body = request("GET", "/latest").json()
    assert [item["status"] for item in body["series"]] == [
        "fresh",
        "stale",
        "stale",
        "fresh",
        "missing",
        "missing",
    ]
    assert body["data"] == "stale"
    assert all(item["value"] == 12 for item in body["series"][:4])


@pytest.mark.parametrize(
    "index,series", [("current", (2606, "flow")), ("jonction", (2170, "turbidity"))]
)
def test_indices_remain_unavailable_for_stale_input(index, series):
    store(series, [(NOW - timedelta(minutes=31), 123)])
    body = request("GET", "/latest").json()
    assert body["indices"][index] == {"status": "unavailable", "reason": "data_stale"}


@pytest.mark.parametrize("series", SERIES)
def test_history_accepts_each_confirmed_series_and_empty_windows(series):
    response = history_response(station=series[0], param=series[1])
    assert response.status_code == 200
    body = response.json()
    assert (body["station_id"], body["parameter"]) == series
    assert body["unit"] == UNITS[series[1]]
    assert body["points"] == []
    assert body["status"] == "missing"
    assert body["latest_at"] is None
    assert body["generated_at"] == body["to"]


def test_history_orders_real_points_and_filters_series_and_inclusive_bounds():
    start = NOW - timedelta(days=1)
    store(
        (2606, "flow"),
        [
            (NOW, 2),
            (start - timedelta(microseconds=1), 999),
            (start, 0),
            (NOW - timedelta(hours=3), 1),
            (NOW + timedelta(microseconds=1), 999),
        ],
    )
    store((2170, "flow"), [(NOW, 999)])
    store((2606, "temperature"), [(NOW, 999)])
    response = history_response()
    assert response.status_code == 200
    body = response.json()
    assert [point["value"] for point in body["points"]] == [0, 1, 2]
    assert [datetime.fromisoformat(point["ts"]) for point in body["points"]] == [
        start,
        NOW - timedelta(hours=3),
        NOW,
    ]
    assert body["status"] == "fresh"
    assert body["latest_at"] == body["to"]


def test_history_normalizes_offset_bounds_and_measurements_to_utc():
    offset = timezone(timedelta(hours=2))
    start = (NOW - timedelta(hours=1)).astimezone(offset)
    store((2170, "turbidity"), [(NOW.astimezone(offset), 0)])
    response = history_response(station=2170, param="turbidity", **{"from": start.isoformat()})
    assert response.status_code == 200
    body = response.json()
    assert body["from"] == (NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    assert body["points"] == [{"ts": NOW.isoformat().replace("+00:00", "Z"), "value": 0}]
    assert body["unit"] == "BSTU"


def test_history_accepts_iso_timestamp_with_minutes_and_timezone():
    response = history_response(**{"from": "2026-11-04T11:00Z"})
    assert response.status_code == 200
    assert response.json()["from"] == "2026-11-04T11:00:00Z"


@pytest.mark.parametrize(
    "age,status",
    [(timedelta(minutes=30), "fresh"), (timedelta(minutes=30, microseconds=1), "stale")],
)
def test_history_freshness_uses_last_returned_point(age, status):
    store((2606, "flow"), [(NOW - age, 12)])
    response = history_response()
    assert response.status_code == 200
    assert response.json()["status"] == status


def test_history_window_without_points_is_missing_even_when_older_measurements_exist():
    store((2606, "flow"), [(NOW - timedelta(minutes=2), 12)])
    response = history_response(**{"from": (NOW - timedelta(minutes=1)).isoformat()})
    assert response.status_code == 200
    assert response.json()["status"] == "missing"
    assert response.json()["latest_at"] is None
    assert response.json()["points"] == []


@pytest.mark.parametrize("start", [NOW - timedelta(days=30), NOW])
def test_history_accepts_exact_time_bounds(start):
    store((2606, "flow"), [(start, 12)])
    response = history_response(**{"from": start.isoformat()})
    assert response.status_code == 200
    assert len(response.json()["points"]) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"station": 9999},
        {"station": 0},
        {"station": "2606; DROP TABLE measurements"},
        {"station": 2606, "param": "height"},
        {"station": 2606, "param": "turbidity"},
        {"param": "flow' OR 1=1 --"},
        {"param": "unknown"},
        {"from": "2026-11-04"},
        {"from": "2026-11-04T11:00:00"},
        {"from": "not-a-date"},
        {"from": "1793793600"},
        {"from": "2026-11-04T11:00:00+99:00"},
        {"from": "2026-11-04T11:00:00Z' OR 1=1 --"},
        {"from": "0001-01-01T00:00:00+01:00"},
        {"from": "9999-12-31T23:59:59-01:00"},
        {"from": (NOW + timedelta(microseconds=1)).isoformat()},
        {"from": (NOW - timedelta(days=30, microseconds=1)).isoformat()},
    ],
)
def test_history_rejects_invalid_inputs_before_accessing_database(monkeypatch, overrides):
    monkeypatch.setenv("PGHOST", "127.0.0.1")
    monkeypatch.setenv("PGPORT", "1")
    response = history_response(**overrides)
    assert response.status_code == 422


@pytest.mark.parametrize("missing", ["station", "param", "from"])
def test_history_requires_all_parameters(missing):
    params = {"station": 2606, "param": "flow", "from": NOW.isoformat()}
    del params[missing]
    assert request("GET", "/history", params).status_code == 422


@pytest.mark.parametrize("count,expected_status", [(5000, 200), (5001, 422)])
def test_history_enforces_point_cap_without_silent_truncation(count, expected_status):
    with connect() as connection:
        connection.execute(
            "INSERT INTO measurements (station_id, parameter, ts, value) "
            "SELECT 2606, 'flow', %s::timestamptz - n * interval '1 second', n "
            "FROM generate_series(1, %s) AS n",
            (NOW, count),
        )
    response = history_response()
    assert response.status_code == expected_status
    if expected_status == 200:
        assert len(response.json()["points"]) == count
    else:
        assert response.json() == {
            "detail": "History exceeds 5000 points; request a more recent from timestamp"
        }
        assert "points" not in response.json()


@pytest.mark.parametrize("path", ["/latest", "/history"])
def test_measurement_routes_hide_database_errors_and_recover(monkeypatch, path):
    def get():
        return request("GET", path) if path == "/latest" else history_response()

    with monkeypatch.context() as environment:
        environment.setenv("PGHOST", "127.0.0.1")
        environment.setenv("PGPORT", "1")
        response = get()
    assert response.status_code == 503
    assert response.json() == {"detail": "Measurements are temporarily unavailable"}
    assert get().status_code == 200


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("path", ["/latest", "/history"])
def test_measurement_routes_reject_writes(method, path):
    assert request(method, path).status_code == 405
    with connect() as connection:
        assert connection.execute("SELECT count(*) FROM measurements").fetchone() == (0,)


def test_openapi_documents_measurement_routes_and_database_unavailability():
    document = request("GET", "/openapi.json").json()
    for path in ("/latest", "/history"):
        assert "503" in document["paths"][path]["get"]["responses"]
        assert set(document["paths"][path]) == {"get"}
    parameters = document["paths"]["/history"]["get"]["parameters"]
    assert {item["name"] for item in parameters if item["required"]} == {
        "station",
        "param",
        "from",
    }
