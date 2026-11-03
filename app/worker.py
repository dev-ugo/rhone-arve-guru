"""Collect immediately, then every ten minutes; recover after bounded failures."""

import argparse
import logging
import signal
from datetime import UTC, datetime, timedelta
from threading import Event
from time import monotonic

import httpx
import psycopg

from app.persistence import get_cursor, record_cycle, store_batch
from app.series import SERIES
from app.source import ExistenzSource, SourceError

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = 600
INITIAL_HISTORY = timedelta(hours=24)
OVERLAP = timedelta(hours=2)
MAX_LOOKBACK = timedelta(days=30)


def backfill_start(cursor: datetime | None, now: datetime) -> datetime:
    start = cursor - OVERLAP if cursor else now - INITIAL_HISTORY
    # Clamp clock regressions as well as outages beyond the source retention.
    return max(now - MAX_LOOKBACK, min(start, now - OVERLAP))


def run_cycle(
    source: ExistenzSource, now: datetime | None = None, stop: Event | None = None
) -> bool:
    end = (now or datetime.now(UTC)).astimezone(UTC)
    success = True
    for series in SERIES:
        if stop is not None and stop.is_set():
            return False
        try:
            cursor = get_cursor(series)
            if cursor and cursor - OVERLAP < end - MAX_LOOKBACK:
                logger.warning("Backfill clipped to 30 days for %s; older gaps may remain", series)
            start = backfill_start(cursor, end)
            batch = source.fetch(series, start, end)
            inserted = store_batch(series, batch, end)
            logger.info(
                "Series %s: inserted=%d received=%d rejected=%d window=%s/%s",
                series,
                inserted,
                len(batch.measurements),
                batch.rejected,
                start,
                end,
            )
            if batch.rejected:
                success = False
        except (SourceError, psycopg.Error):
            # Do not log connection strings or potentially sensitive response bodies.
            logger.warning("Ingestion failed for %s; retrying next cycle", series)
            success = False
    try:
        record_cycle(datetime.now(UTC), success)
    except psycopg.Error:
        logger.warning("Cannot persist worker heartbeat; retrying next cycle")
        success = False
    return success


def run_forever(source: ExistenzSource, stop: Event) -> None:
    while not stop.is_set():
        started = monotonic()
        run_cycle(source, stop=stop)
        stop.wait(max(0, INTERVAL_SECONDS - (monotonic() - started)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run one ingestion cycle and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop = Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    with httpx.Client(timeout=httpx.Timeout(20, connect=5), follow_redirects=False) as client:
        source = ExistenzSource(client)
        if args.once:
            return 0 if run_cycle(source) else 1
        run_forever(source, stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
