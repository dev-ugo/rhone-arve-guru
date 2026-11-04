"""Read-only measurement API and independent worker and data health signals."""

from typing import Literal

import psycopg
from fastapi import FastAPI, Response

from app import __version__
from app.database import check_database
from app.health import IngestionHealth, ingestion_health
from app.measurements import router as measurements_router

app = FastAPI(title="Rhône & Arve Guru", version=__version__)
app.include_router(measurements_router)


class Health(IngestionHealth):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok", "unavailable"]


@app.get("/")
def index() -> dict[str, str]:
    return {"name": app.title, "version": __version__, "stage": "api", "docs": "/docs"}


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
