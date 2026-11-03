# Rhône & Arve Guru

A public dashboard project for the Rhône and Arve in Geneva. The current milestone
provides the containerized development foundation: FastAPI, PostgreSQL, readiness
checks, and isolated tests. Measurement ingestion, the history API, indices, and
the dashboard are not implemented yet.

## Requirements

Install and start Docker with Docker Compose v2 (2.20 or later). On Windows or
macOS, Docker Desktop provides both; select Linux containers. No local Python,
PostgreSQL, Node.js, or Make installation is required. The first build needs
internet access to download images and Python packages.

## Start

From the repository root, in PowerShell or a POSIX shell:

```sh
docker compose up --build -d --wait
```

Open [API documentation](http://localhost:8000/docs), the
[bootstrap endpoint](http://localhost:8000/), or [health](http://localhost:8000/health).
Alternatively, `docker compose up --build` starts in the foreground with logs.
PostgreSQL must become healthy before the API starts.

```sh
docker compose ps
docker compose logs -f
docker compose down
```

Routine shutdown retains the `postgres-data` volume. PostgreSQL has no published
host port; the API binds only to `127.0.0.1`. These defaults are for local
development, not a public deployment.

## Configuration

Compose works without an `.env` file. To override defaults, copy `.env.example`
to `.env` (`Copy-Item .env.example .env` in PowerShell or `cp .env.example .env`
in a POSIX shell), edit it, and run the start command again.

| Variable | Default | Purpose |
| --- | --- | --- |
| `API_PORT` | `8000` | API port on localhost |
| `POSTGRES_DB` | `rhone_arve` | Development database name |
| `POSTGRES_USER` | `rhone_arve` | Development database user |
| `POSTGRES_PASSWORD` | `local-development-only` | Development-only password |

Credentials are passed as separate standard `PG*` environment variables, so
passwords do not need URL encoding. PostgreSQL initialization variables apply
only when the volume is empty: changing `.env` does not change existing database
credentials. Keep matching credentials or change them in PostgreSQL explicitly.
Never commit `.env` or use the sample password on a public server.

There is no measurement schema or migration yet. Versioned migrations will be
introduced with persistence; startup currently initializes only PostgreSQL's
database and user.

## Develop and verify

Enable automatic Python source reload without rebuilding for each edit:

```sh
docker compose -f compose.yaml -f compose.dev.yaml up --build -d --wait
```

Source files are mounted read-only. Changes to dependencies still need a rebuild.
To return to the normal configuration, run the standard start command.

Run lint, formatting checks, and tests inside a separate Compose project:

```sh
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yaml down
```

The first command returns the test exit code. Run the second even after a failure
to clean up test containers. Tests use real PostgreSQL in temporary memory storage
and never connect to the development database or the public source API. They check
readiness, connection failure, and recovery. No host ports are needed.

Validate all Compose configurations without starting containers:

```sh
docker compose config --quiet
docker compose -f compose.yaml -f compose.dev.yaml config --quiet
docker compose -f compose.test.yaml config --quiet
```

If Make is already available, optional shortcuts are `make up`, `make dev`,
`make down`, `make logs`, `make ps`, `make test`, and `make check`.
`make help` lists them. If tests fail, use `make test-down` after investigating.
All commands above work without Make.

Direct dependencies are pinned in `requirements.txt` and `requirements-dev.txt`;
shared transitive constraints live in `requirements-lock.txt`. When updating,
edit the direct pins, temporarily remove the constraint line from
`requirements.txt`, rebuild the test image, and inspect the resolved versions:

```sh
docker compose -f compose.test.yaml build tests
docker compose -f compose.test.yaml run --rm --no-deps tests pip freeze
```

Replace the constraints with that output, restore the constraint line, rebuild,
and run the tests. No package installation on the host is needed. Base images
track Python 3.13 and PostgreSQL 17 within Debian Bookworm for patch updates.

## Health contract and next milestones

`GET /health` returns HTTP 200 when a bounded PostgreSQL query succeeds, or HTTP
503 when connectivity fails. `status` describes infrastructure readiness only.
`worker: "not_implemented"` and `data: "unavailable"` explicitly prevent readiness
from being interpreted as current measurement availability. No source health
endpoint is used as a substitute for per-series freshness.

Next milestones are scheduled ingestion with idempotent storage and backfill,
`/latest` and `/history`, per-series freshness and worker health, then the mobile
dashboard. No current or contrast thresholds are calibrated. The MVP's 24-hour
worker observation and `/latest` latency target remain unverified.

Measurements will originate from the [Federal Office for the Environment (FOEN)](https://www.hydrodaten.admin.ch/)
through [Existenz](https://api.existenz.ch/). The application does not replace
official guidance and cannot determine whether swimming is permitted or safe.

Compose startup uses Docker's documented
[health dependency handling](https://docs.docker.com/compose/how-tos/startup-order/).
