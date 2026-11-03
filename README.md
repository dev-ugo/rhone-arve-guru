# Rhône & Arve Guru

A public dashboard project for the Rhône and Arve in Geneva. The current milestone
provides scheduled ingestion of six measurement series, PostgreSQL storage with
idempotent backfill, FastAPI health reporting, and isolated tests. The measurement
API routes, indices, and dashboard are not implemented yet.

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
PostgreSQL must become healthy and versioned migrations must complete before the
API and worker start. The worker loads the last 24 hours immediately, then ingests
every ten minutes. An unavailable public source does not prevent the API starting.

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

Versioned SQL migrations run automatically through the one-shot `migrate` service,
including on existing database volumes. See [ingestion and storage](docs/ingestion.md)
for the schema, backfill policy, failure handling, and manual commands.

## Develop and verify

Enable automatic Python source reload without rebuilding for each edit:

```sh
docker compose -f compose.yaml -f compose.dev.yaml up --build -d --wait
```

Source files are mounted read-only. The API reloads automatically; restart the
worker after Python edits with `docker compose restart worker`. New migrations
require `docker compose run --rm migrate`, then restart affected services. Changes
to dependencies still need a rebuild.
To return to the normal configuration, run the standard start command.

Run lint, formatting checks, and tests inside a separate Compose project:

```sh
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yaml down
```

The first command returns the test exit code. Run the second even after a failure
to clean up test containers. Tests use real PostgreSQL in temporary memory storage
and never connect to the development database or the public source API. They check
readiness, per-series freshness, migrations, duplicate prevention, bounded HTTP
requests, malformed or partial responses, backfill, and recovery after source or
database outages. No host ports are needed.

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

## Security checks

The `Security` GitHub Actions workflow runs on every pull request (all target
branches), every push to `main`, and manual dispatch. It has three independent,
failing checks:

- **Python security (Bandit)** scans application Python code, including low
  severity and low confidence findings.
- **Python dependencies (pip-audit)** audits all pinned runtime and test packages
  in `requirements-lock.txt`, including transitive dependencies. Any known
  vulnerability or package lookup failure fails the check. Keep this complete
  constraint inventory synchronized when changing dependencies. Application
  packages are neither installed nor executed during the audit. A second audit
  checks the installed security tools and their own transitive dependencies.
- **Git history secrets (Gitleaks)** scans all fetched Git history, including
  deleted files and earlier commits. Checkout fetches the complete history;
  detected secret values are redacted in logs. No historical baseline or blanket
  path exclusions suppress findings.

Run the same checks locally in PowerShell or a POSIX shell, using only Docker:

```sh
docker compose -f compose.security.yaml run --build --rm --no-deps code
docker compose -f compose.security.yaml run --build --rm --no-deps dependencies
docker compose -f compose.security.yaml run --rm --no-deps secrets
docker compose -f compose.security.yaml down
```

Run each command even if another fails to see all results. The secrets command
checks committed history, so commit intended changes before the final scan;
untracked and uncommitted files are not covered. It mounts the checkout read-only
at runtime; `.git` and local working materials never enter Docker build contexts.
The dedicated security image does not change runtime or test dependencies.
Auditing needs internet access to the public advisory service; Bandit and Gitleaks
scan locally once their images are available. Network failures must be resolved
and the dependency check rerun, rather than treated as a clean audit.

Actions use a read-only repository token, do not persist checkout credentials,
and have bounded run times. Pull requests use `pull_request`, with no project
secrets or privileged `pull_request_target` execution. Checkout is pinned to a
commit; Python scanner versions and the Gitleaks image version are pinned.
Dependabot checks Python packages, Actions, Dockerfiles, and Compose images weekly
and proposes updates without automatically merging them. Review the constraints
and run application tests with dependency updates.

After this branch and its Docker bootstrap prerequisite reach `main`, configure
a GitHub ruleset or branch protection for `main` to require the three named checks
above before merging, and restrict bypasses/direct pushes as appropriate. The
workflow reports failures; repository settings enforce merge blocking. These
settings are not enabled by committing this file. The first hosted run remains
to be verified after publication.

If a real credential is detected, revoke or rotate it first. Removing it from the
latest file does not remove exposure or clean historical findings. Coordinate
any history cleanup separately; do not add an ignore rule for an active secret.
The sample local database passwords are intentionally public development values,
never production credentials. Any false-positive exception must be narrowly
scoped, reviewed, and documented with a reason; no exceptions are configured.

This minimum workflow detects common insecure Python patterns, known Python
package vulnerabilities, and recognizable committed secrets. It does not replace
manual review, detect every credential, or audit operating-system packages in
container images. Tool references: [Bandit](https://bandit.readthedocs.io/),
[pip-audit](https://github.com/pypa/pip-audit), and
[Gitleaks](https://github.com/gitleaks/gitleaks).

## Health contract and next milestones

`GET /health` returns HTTP 200 when a bounded PostgreSQL query succeeds, or HTTP
503 when the database or ingestion schema is unavailable. `status` describes
infrastructure readiness only. `worker` reports the latest cycle independently
from `data`; `series` provides measurement timestamps, original source units, and
fresh/stale/missing status for each of the six expected series. Data is fresh for
30 minutes after measurement; this operational limit is not a safety threshold.
No source health endpoint substitutes for per-series freshness. See the detailed
[health contract](docs/ingestion.md#health).

Next milestones are `/latest` and `/history`, then the mobile dashboard.
No current or contrast thresholds are calibrated. The MVP's 24-hour
worker observation and `/latest` latency target remain unverified.

Measurements will originate from the [Federal Office for the Environment (FOEN)](https://www.hydrodaten.admin.ch/)
through [Existenz](https://api.existenz.ch/). The application does not replace
official guidance and cannot determine whether swimming is permitted or safe.

Compose startup uses Docker's documented
[health dependency handling](https://docs.docker.com/compose/how-tos/startup-order/).
