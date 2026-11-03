"""Bounded Existenz access and strict validation of individual source readings."""

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app import __version__
from app.series import SERIES

BASE_URL = "https://api.existenz.ch/apiv1/hydro"
MAX_RESPONSE_BYTES = 5_000_000


class SourceError(Exception):
    """A source request or response could not be used."""


@dataclass(frozen=True)
class Measurement:
    station_id: int
    parameter: str
    ts: datetime
    value: float


@dataclass(frozen=True)
class Batch:
    measurements: list[Measurement]
    rejected: int


def parse_payload(
    document: object, series: tuple[int, str], start: datetime, end: datetime
) -> Batch:
    """Keep valid readings and count invalid rows without inventing observations."""
    if not isinstance(document, dict) or not isinstance(document.get("payload"), list):
        raise SourceError("Expected an object containing a payload array")
    measurements = []
    rejected = 0
    for row in document["payload"]:
        try:
            if not isinstance(row, dict):
                raise ValueError("Expected a reading object")
            if row.get("loc") != str(series[0]) or row.get("par") != series[1]:
                raise ValueError("Unexpected series")
            timestamp, value = row.get("timestamp"), row.get("val")
            if type(timestamp) not in (int, float) or type(value) not in (int, float):
                raise ValueError("Expected numeric timestamp and value")
            if not math.isfinite(timestamp) or not math.isfinite(value):
                raise ValueError("Non-finite reading")
            ts = datetime.fromtimestamp(timestamp, UTC)
            if not start <= ts <= end:
                raise ValueError("Timestamp outside requested bounds")
            measurements.append(Measurement(series[0], series[1], ts, float(value)))
        except (ValueError, OverflowError, OSError):
            rejected += 1
    return Batch(measurements, rejected)


class ExistenzSource:
    def __init__(self, client: httpx.Client):
        self.client = client

    def fetch(self, series: tuple[int, str], start: datetime, end: datetime) -> Batch:
        if series not in SERIES or start.utcoffset() is None or end.utcoffset() is None:
            raise ValueError("Expected a supported series and timezone-aware bounds")
        if start >= end:
            raise ValueError("Expected increasing bounds")
        params = {
            "locations": str(series[0]),
            "parameters": series[1],
            "startdate": start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "enddate": end.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "app": "rhone-arve-guru",
            "version": __version__,
        }
        try:
            with self.client.stream("GET", f"{BASE_URL}/daterange", params=params) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise SourceError("Source response exceeds size limit")
            document = json.loads(content)
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError("Source request failed or returned invalid JSON") from exc
        return parse_payload(document, series, start, end)
