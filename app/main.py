"""Initial API and infrastructure readiness endpoint."""

from typing import Literal

import psycopg
from fastapi import FastAPI, Response
from pydantic import BaseModel

from app import __version__
from app.database import check_database

app = FastAPI(title="Rhône & Arve Guru", version=__version__)


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok", "unavailable"]
    worker: Literal["not_implemented"] = "not_implemented"
    data: Literal["unavailable"] = "unavailable"


@app.get("/")
def index() -> dict[str, str]:
    return {"name": app.title, "version": __version__, "stage": "bootstrap", "docs": "/docs"}


@app.get("/health", response_model=Health, responses={503: {"model": Health}})
def health(response: Response) -> Health:
    """Report infrastructure readiness, without claiming worker or data health."""
    try:
        check_database()
    except psycopg.Error:
        response.status_code = 503
        return Health(status="degraded", version=__version__, database="unavailable")
    return Health(status="ok", version=__version__, database="ok")
