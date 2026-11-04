"""Read-only measurement API and independent worker and data health signals."""

from pathlib import Path
from typing import Literal

import psycopg
from fastapi import FastAPI, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from app import __version__
from app.database import check_database
from app.health import IngestionHealth, ingestion_health
from app.measurements import router as measurements_router

app = FastAPI(title="Rhône & Arve Guru", version=__version__)
app.include_router(measurements_router)
STATIC_DIRECTORY = Path(__file__).parent / "static"
DASHBOARD_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class DashboardFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers.update(DASHBOARD_HEADERS)
        return response


app.mount("/static", DashboardFiles(directory=STATIC_DIRECTORY), name="static")


class Health(IngestionHealth):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok", "unavailable"]


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the dashboard without requiring a database or a public source request."""
    return FileResponse(STATIC_DIRECTORY / "index.html", headers=DASHBOARD_HEADERS)


@app.get("/health", response_model=Health, responses={503: {"model": Health}})
def health(response: Response) -> Health:
    """HTTP status reports infrastructure readiness; data health is explicit in the body."""
    try:
        check_database()
        ingestion = ingestion_health()
    except psycopg.Error:
        response.status_code = 503
        return Health(status="degraded", version=__version__, database="unavailable")
    return Health(status="ok", version=__version__, database="ok", **ingestion.model_dump())
