"""Exercise ingestion, partial failure, outage recovery, and scheduling offline."""

from datetime import UTC, datetime, timedelta
from threading import Event

import httpx

from app.database import connect
from app.health import check_worker
from app.persistence import get_cursor, record_cycle
from app.series import SERIES
from app.source import ExistenzSource
from app.worker import backfill_start, run_cycle, run_forever

NOW = datetime(2026, 1, 10, 12, tzinfo=UTC)


def reading(request, ts, value=123):
    return {
        "loc": request.url.params["locations"],
        "par": request.url.params["parameters"],
        "timestamp": ts.timestamp(),
        "val": value,
    }


def test_six_series_and_repeated_cycles_are_idempotent():
    def respond(request):
        return httpx.Response(200, json={"payload": [reading(request, NOW)]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert run_cycle(ExistenzSource(client), NOW)
        assert run_cycle(ExistenzSource(client), NOW)
    with connect() as connection:
        assert connection.execute("SELECT count(*) FROM measurements").fetchone()[0] == 6
        assert connection.execute("SELECT status FROM worker_state").fetchone()[0] == "ok"
    assert all(get_cursor(series) == NOW for series in SERIES)


def test_source_outage_recovers_history_older_than_initial_window():
    outage = False
    end = NOW
    starts = []

    def respond(request):
        starts.append(datetime.fromisoformat(request.url.params["startdate"]))
        if outage:
            return httpx.Response(503)
        timestamps = [NOW] if end == NOW else [NOW, NOW + timedelta(hours=1), end]
        return httpx.Response(200, json={"payload": [reading(request, ts) for ts in timestamps]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        source = ExistenzSource(client)
        assert run_cycle(source, NOW)
        assert starts == [NOW - timedelta(hours=24)] * 6
        starts.clear()
        outage = True
        end = NOW + timedelta(days=2)
        assert not run_cycle(source, end)
        assert all(get_cursor(series) == NOW for series in SERIES)
        with connect() as connection:
            assert connection.execute("SELECT status FROM worker_state").fetchone()[0] == "error"
        outage = False
        starts.clear()
        assert run_cycle(source, end)
    assert starts == [NOW - timedelta(hours=2)] * 6
    with connect() as connection:
        assert connection.execute("SELECT count(*) FROM measurements").fetchone()[0] == 18
        assert connection.execute("SELECT status FROM worker_state").fetchone()[0] == "ok"


def test_partial_invalid_empty_and_failed_series_do_not_block_others():
    def respond(request):
        series = (int(request.url.params["locations"]), request.url.params["parameters"])
        if series == (2606, "flow"):
            return httpx.Response(
                200, json={"payload": [reading(request, NOW), reading(request, NOW, None)]}
            )
        if series == (2606, "temperature"):
            return httpx.Response(200, json={"payload": []})
        if series == (2170, "turbidity"):
            return httpx.Response(503)
        return httpx.Response(200, json={"payload": [reading(request, NOW)]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert not run_cycle(ExistenzSource(client), NOW)
    assert get_cursor((2606, "flow")) is None
    assert get_cursor((2606, "temperature")) is None
    assert get_cursor((2170, "turbidity")) is None
    assert get_cursor((2170, "height")) == NOW
    with connect() as connection:
        assert connection.execute("SELECT count(*) FROM measurements").fetchone()[0] == 4


def test_database_outage_does_not_stop_worker_and_next_cycle_recovers(monkeypatch):
    def respond(request):
        return httpx.Response(200, json={"payload": [reading(request, NOW)]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        source = ExistenzSource(client)
        with monkeypatch.context() as environment:
            environment.setenv("PGHOST", "127.0.0.1")
            environment.setenv("PGPORT", "1")
            assert not run_cycle(source, NOW)
        assert run_cycle(source, NOW)
    assert all(get_cursor(series) == NOW for series in SERIES)


def test_backfill_retention_and_clock_regression_are_bounded():
    assert backfill_start(NOW - timedelta(days=40), NOW) == NOW - timedelta(days=30)
    assert backfill_start(NOW + timedelta(days=1), NOW) == NOW - timedelta(hours=2)


def test_worker_liveness_tracks_cycles_even_during_source_failure():
    assert not check_worker()
    record_cycle(datetime.now(UTC), False)
    assert check_worker()
    record_cycle(datetime.now(UTC) - timedelta(minutes=31), True)
    assert not check_worker()


def test_scheduler_retries_after_failed_cycle_and_waits_ten_minutes(monkeypatch):
    stop = Event()
    calls = []
    waits = []

    def cycle(source, stop):
        calls.append(source)
        if len(calls) == 2:
            stop.set()
        return len(calls) == 2

    def wait(seconds):
        waits.append(seconds)

    monkeypatch.setattr("app.worker.run_cycle", cycle)
    monkeypatch.setattr(stop, "wait", wait)
    times = iter([0, 3, 600, 620])
    monkeypatch.setattr("app.worker.monotonic", lambda: next(times))
    source = object()
    run_forever(source, stop)
    assert calls == [source, source]
    assert waits == [597, 580]
