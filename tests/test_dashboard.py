"""Check the browser-facing asset boundary without public network requests."""

import asyncio

import httpx
import pytest

from app.main import app


def get(path: str) -> httpx.Response:
    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get(path)

    return asyncio.run(request())


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/", "text/html"),
        ("/static/dashboard.css", "text/css"),
        ("/static/dashboard.js", "javascript"),
        ("/static/dashboard-model.mjs", "javascript"),
        ("/static/river.svg", "image/svg+xml"),
    ],
)
def test_dashboard_assets_have_browser_security_headers(path, content_type):
    response = get(path)
    assert response.status_code == 200
    assert content_type in response.headers["content-type"]
    policy = response.headers["content-security-policy"]
    assert "default-src 'none'" in policy
    assert "connect-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_dashboard_stays_available_during_database_failure(monkeypatch):
    monkeypatch.setenv("PGHOST", "127.0.0.1")
    monkeypatch.setenv("PGPORT", "1")
    response = get("/")
    assert response.status_code == 200
    assert '<html lang="fr">' in response.text
    assert "ne remplace pas les consignes officielles" in response.text
    assert get("/latest").status_code == 503


@pytest.mark.parametrize("path", ["/static/..%2Fmain.py", "/static/.env", "/static/README.md"])
def test_static_mount_does_not_expose_application_or_repository_files(path):
    response = get(path)
    assert response.status_code == 404
    assert "PGPASSWORD" not in response.text


def test_dashboard_policy_does_not_break_interactive_api_documentation():
    response = get("/docs")
    assert response.status_code == 200
    assert "swagger-ui" in response.text
    assert "content-security-policy" not in response.headers
