"""Exercise readiness against real PostgreSQL and a refused connection."""

import asyncio

import httpx

from app.main import app


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
    assert response.json()["stage"] == "bootstrap"
    assert get(response.json()["docs"]).status_code == 200


def test_health_checks_real_postgresql():
    response = get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "database": "ok",
        "worker": "not_implemented",
        "data": "unavailable",
    }


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
