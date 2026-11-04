"""Exercise readiness against real PostgreSQL and a refused connection."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from app.database import connect
from app.main import app
from app.persistence import record_cycle, store_batch
from app.series import SERIES
from app.source import Batch, Measurement


def get(path: str) -> httpx.Response:
    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get(path)

    return asyncio.run(request())


def test_bootstrap_links_to_api_documentation():
    response = get("/")
    assert response.status_code == 200
    assert response.json()["stage"] == "api"
    assert get(response.json()["docs"]).status_code == 200


def test_health_checks_real_postgresql():
    response = get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == body["database"] == "ok"
    assert body["version"] == "0.2.0"
    assert body["worker"] == "starting"
    assert body["worker_finished_at"] is None
    assert body["data"] == "unavailable"
    assert len(body["series"]) == 6
    assert all(s["status"] == "missing" and s["latest_at"] is None for s in body["series"])


def test_health_recovers_after_database_connection_failure(monkeypatch):
    with monkeypatch.context() as environment:
        environment.setenv("PGHOST", "127.0.0.1")
        environment.setenv("PGPORT", "1")
        response = get("/health")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"
    assert response.json()["status"] == "degraded"
    assert "password" not in response.text.lower()
    assert get("/health").status_code == 200


def test_freshness_is_independent_per_series_and_worker_execution():
    now = datetime.now(UTC)
    for series in SERIES:
        store_batch(series, Batch([Measurement(*series, now - timedelta(minutes=5), 12)], 0), now)
    record_cycle(now, False)
    body = get("/health").json()
    assert body["worker"] == "error"
    assert body["data"] == "fresh"
    assert {s["parameter"]: s["unit"] for s in body["series"]} == {
        "flow": "m3/s",
        "temperature": "°C",
        "height": "m",
        "turbidity": "BSTU",
    }
    with connect() as connection:
        connection.execute(
            "UPDATE measurements SET ts = %s WHERE station_id = 2606 AND parameter = 'flow'",
            (now - timedelta(minutes=31),),
        )
        connection.execute("DELETE FROM measurements WHERE parameter = 'turbidity'")
    record_cycle(now - timedelta(minutes=31), True)
    body = get("/health").json()
    states = {(s["station_id"], s["parameter"]): s["status"] for s in body["series"]}
    assert states[(2606, "flow")] == "stale"
    assert states[(2606, "temperature")] == "fresh"
    assert states[(2170, "turbidity")] == "missing"
    assert body["data"] == body["worker"] == "stale"
