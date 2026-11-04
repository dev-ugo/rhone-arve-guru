# Measurement ingestion and storage

The worker reads [Existenz hydrology data](https://api.existenz.ch/) originating
from the [Federal Office for the Environment (FOEN)](https://www.hydrodaten.admin.ch/).
Every request includes `app=rhone-arve-guru` and the application version.
The application does not replace official guidance and cannot establish whether
swimming is permitted or safe.

## Source contract

`GET https://api.existenz.ch/apiv1/hydro/daterange` receives one station and one
parameter per request, with explicit ISO 8601 UTC `startdate` and `enddate`.
The default response is an object with a `payload` array. Each reading maps as
follows: `loc` (source station code) to `station_id`, `par` to `parameter`, Unix
seconds `timestamp` to UTC `ts`, and numeric `val` to `value`.

| Station | Parameter | Original Existenz catalog unit |
| --- | --- | --- |
| Rhône 2606 | `flow` | `m3/s` |
| Rhône 2606 | `temperature` | `°C` |
| Arve 2170 | `flow` | `m3/s` |
| Arve 2170 | `temperature` | `°C` |
| Arve 2170 | `height` | `m` (water-surface elevation, not depth) |
| Arve 2170 | `turbidity` | `BSTU` |

The FOEN station page uses NTU for turbidity, while Existenz declares BSTU. Values
are stored unchanged; no equivalence, conversion, or Jonction threshold is assumed.
These catalog units are explicit application metadata, not refreshed dynamically.

The adapter rejects wrong stations or parameters, missing fields, nonnumeric or
nonfinite values, invalid timestamps, and readings outside the requested window.
Zero is accepted only when explicitly received as a valid measurement. Invalid
rows are counted and skipped while valid rows are retained; invalid response
envelopes fail the request. No interpolation or default observations fill gaps.

HTTP timeouts are five seconds to connect and twenty seconds for read, write, or
pool inactivity. Responses are limited to 5 MB; redirects are rejected. Requests
are sequential, six per cycle, without immediate retries. These are inactivity
timeouts rather than a total cycle deadline. Cycles start every 600 seconds using
a monotonic clock; if a cycle overruns, the next starts after it completes. SIGINT
and SIGTERM interrupt the wait and stop before the next series; an in-flight
request completes or times out first. Docker may terminate a request after its
stop timeout; completed per-series transactions remain committed.

## Backfill and failures

The first successful load covers the previous 24 hours. Each series then has its
own persistent `covered_until` cursor. Its next request starts two hours before
that cursor and ends at the current UTC time. This overlap rechecks delayed
readings; `/latest` is not used because it cannot recover missed history.

Valid readings and cursor progress commit in one transaction. Empty responses or
any rejected rows retain the prior cursor so that the next cycle retries coverage.
An empty series with no prior cursor continues requesting the last 24 hours.
A successful nonempty response advances coverage even if the source itself has
gaps; gaps are not proof of a client failure. Readings delayed by more than the
two-hour overlap may therefore remain missing after coverage has advanced.

After an outage, requests resume from each persisted cursor, limited to the last
30 days to remain within Existenz's documented 32-day archive. Clipping is logged;
older gaps cannot be recovered automatically. On a new installation, history
before the initial 24-hour window is not imported. Future cursors caused by clock
regression are clamped to a two-hour lookback.

An HTTP, JSON, validation, or PostgreSQL failure in one series does not block the
others. Source and database failures are retried on the next cycle; connection
details and response bodies are not logged. A completed cycle records a heartbeat
and `ok` or `error`. Empty valid responses can produce a successful cycle with
missing data. The API reports these states separately.

## Schema and migrations

`app/migrations/001_ingestion.sql` creates:

- `measurements(station_id, parameter, ts, value)`, with a composite primary key,
  `timestamptz` instants, and finite double precision values. A check constraint
  permits only the six confirmed station/parameter pairs.
- `ingestion_cursors(station_id, parameter, covered_until)` for successful coverage.
- `worker_state(id, finished_at, status)` for the latest completed cycle.

Inserts use parameterized SQL and `ON CONFLICT (station_id, parameter, ts) DO NOTHING`.
Repeated or overlapping requests never duplicate or overwrite a stored reading.
Upstream corrections of existing keys are deliberately not applied.

`python -m app.migrate` applies ordered SQL files transactionally and records their
filenames in `schema_migrations`. A PostgreSQL advisory transaction lock serializes
migration attempts. Migrations are additive and run on existing volumes as well
as new ones; do not edit applied migrations or remove development volumes to
upgrade. Add a new numbered migration for subsequent schema changes. Automatic
rollback migrations are not provided.

Start everything from a fresh checkout, without `.env`:

```sh
docker compose up --build -d --wait
docker compose logs --tail 50 worker migrate
```

Reapply pending migrations explicitly when needed:

```sh
docker compose run --rm migrate
```

Run a bounded integration cycle against the real source after startup (six
requests; separate from the automated test suite):

```sh
docker compose run --rm --no-deps worker python -m app.worker --once
```

The command returns nonzero if any series fails or contains invalid rows. Inspect
stored counts and coverage with PostgreSQL inside Docker:

```sh
docker compose exec db psql -U rhone_arve -d rhone_arve -c "SELECT station_id, parameter, count(*), min(ts), max(ts) FROM measurements GROUP BY station_id, parameter ORDER BY station_id, parameter;"
```

Use matching database/user names if defaults were customized. All commands work
in PowerShell or a POSIX shell. Routine `docker compose down` preserves data.

## Health

`GET /health` returns HTTP 200 when the database and ingestion schema can be read,
or 503 when unavailable. HTTP status and top-level `status` report infrastructure
readiness; they do not certify data freshness.

- `worker`: `starting` before any heartbeat, `ok` or `error` for the last completed
  cycle, `stale` after thirty minutes without completion, or `unavailable` when
  the database cannot be read. `worker_finished_at` is its UTC completion time.
- `series`: six entries containing `station_id`, `parameter`, source `unit`,
  `latest_at` (UTC or null), and `status`. A reading is `fresh` when its age is
  between zero and thirty minutes, inclusive; otherwise it is `stale`. A series
  without readings is `missing`.
- `data`: `fresh` only when all six series are fresh, `unavailable` when no
  readings exist or the database is unavailable, and `stale` for other incomplete
  or stale combinations.

Thirty minutes allows three nominal collection intervals. It is an operational
criterion, not a calibrated current/contrast threshold or a safety judgement.
The worker container's healthcheck checks recent completion even if the source
failed; inspect the API body or worker logs for execution errors and data gaps.

## Verification

```sh
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yaml down
```

Tests use an isolated real PostgreSQL database in memory-backed storage and
mocked HTTP responses. They cover migrations on existing data, timezone storage,
constraints and atomic rollback, duplicate suppression, per-series freshness,
invalid and partial payloads, bounded requests, recovery after source and database
outages, historical backfill beyond 24 hours, and the ten-minute retry schedule.
They do not contact Existenz or use the development database.

The read-only `/latest` and `/history` routes expose these stored measurements;
see the [API contract](api.md) for validation, freshness, and bounded history.
The MVP's continuous 24-hour worker observation remains to be performed. Local
response-time verification does not establish public-hosting performance.
