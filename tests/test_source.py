"""Exercise the real HTTP adapter without access to the public API."""

from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest

from app import __version__
from app.source import ExistenzSource, SourceError, parse_payload

END = datetime(2026, 1, 10, 12, tzinfo=UTC)
START = END - timedelta(days=1)
SERIES = (2606, "flow")


def reading(**overrides):
    return {"loc": "2606", "par": "flow", "timestamp": END.timestamp(), "val": 123.4} | overrides


def test_requests_explicit_utc_bounds_series_and_application_version():
    def respond(request):
        assert request.url.path == "/apiv1/hydro/daterange"
        assert dict(request.url.params) == {
            "locations": "2606",
            "parameters": "flow",
            "startdate": "2026-01-09T12:00:00Z",
            "enddate": "2026-01-10T12:00:00Z",
            "app": "rhone-arve-guru",
            "version": __version__,
        }
        assert request.extensions["timeout"] == {"connect": 5, "read": 20, "write": 20, "pool": 20}
        return httpx.Response(200, json={"payload": [reading()]})

    with httpx.Client(
        transport=httpx.MockTransport(respond), timeout=httpx.Timeout(20, connect=5)
    ) as client:
        batch = ExistenzSource(client).fetch(SERIES, START, END)
    assert batch.rejected == 0
    assert batch.measurements[0].ts == END
    assert batch.measurements[0].value == 123.4


@pytest.mark.parametrize(
    "row",
    [
        None,
        [],
        {},
        reading(val=None),
        reading(val="123"),
        reading(val=True),
        reading(val=float("nan")),
        reading(val=float("inf")),
        reading(timestamp=None),
        reading(timestamp=True),
        reading(timestamp=float("nan")),
        reading(timestamp=1e30),
        reading(timestamp=(END + timedelta(seconds=1)).timestamp()),
        reading(timestamp=(START - timedelta(seconds=1)).timestamp()),
        reading(loc="2170"),
        reading(loc=2606),
        reading(par="height"),
    ],
)
def test_invalid_readings_leave_gaps_without_discarding_valid_rows(row):
    batch = parse_payload({"payload": [reading(val=0), row]}, SERIES, START, END)
    assert batch.rejected == 1
    assert len(batch.measurements) == 1
    assert batch.measurements[0].value == 0


@pytest.mark.parametrize("document", [None, [], {}, {"payload": {}}, {"payload": None}])
def test_invalid_envelope_is_not_an_empty_success(document):
    with pytest.raises(SourceError):
        parse_payload(document, SERIES, START, END)


@pytest.mark.parametrize("status,content", [(503, b"outage"), (200, b"not json"), (302, b"")])
def test_http_and_json_failures_are_retryable_source_errors(status, content):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, content=content))
    ) as client:
        with pytest.raises(SourceError):
            ExistenzSource(client).fetch(SERIES, START, END)


def test_network_timeouts_are_retryable():
    def timeout(request):
        raise httpx.ReadTimeout("Simulated outage", request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(SourceError):
            ExistenzSource(client).fetch(SERIES, START, END)


def test_oversized_responses_are_rejected(monkeypatch):
    monkeypatch.setattr("app.source.MAX_RESPONSE_BYTES", 32)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 33))
    ) as client:
        with pytest.raises(SourceError, match="size limit"):
            ExistenzSource(client).fetch(SERIES, START, END)


def test_empty_payload_preserves_absence():
    batch = parse_payload({"payload": []}, SERIES, START, END)
    assert batch.measurements == []
    assert batch.rejected == 0


def test_timezone_offsets_are_normalized_to_utc():
    local_end = END.astimezone(timezone(timedelta(hours=2)))
    batch = parse_payload({"payload": [reading()]}, SERIES, START, local_end)
    assert batch.measurements[0].ts.tzinfo == UTC
