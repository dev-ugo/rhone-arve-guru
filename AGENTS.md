# Working guidelines — Rhône & Arve Guru

These instructions apply to the entire repository and to every agent working in it.

## Project scope and language

- Build a public dashboard for the Rhône and Arve in Geneva, displaying current measurements, a 24-hour chart, and indicative current and Jonction contrast indices.
- The MVP includes scheduled ingestion, historical storage, a REST API, a mobile-readable page, and local Docker Compose startup. Forecasts, accounts, push notifications, and a mobile application are outside the MVP.
- Local planning notes and source investigations may provide additional context, but the public repository must remain understandable, buildable, and testable without them.
- Stay within the MVP scope. V2 features and stack changes require a user request.
- **Write all project code and documentation in English**, including identifiers, comments, docstrings, test descriptions, configuration explanations, and documentation filenames. **Write commit subjects and bodies, branch names, and pull request titles and descriptions in English.**
- Keep conversations with the user in French unless requested otherwise. The language of the public interface is a separate product decision; do not infer it from the repository language.
- Preserve official proper names, source parameter names, external URLs, and raw third-party payloads or documents as received. Do not translate source snapshots or change their values to satisfy the English-language convention.
- Carry each requested task through implementation, verification, and its final commit. Clearly report blockers and checks that could not be performed.

## Git: a dedicated branch and an explicit commit for each feature

1. Before editing, inspect `git status --short`, the current branch, and applicable instructions. Preserve existing changes; do not overwrite, delete, stash, or include unrelated work in a commit.
2. Create a dedicated branch **before starting each new feature**. Apply the same rule to fixes, documentation, and configuration changes.
3. Use `<type>/<short-kebab-case-description>` for branch names: `feat/measurement-ingestion`, `feat/history-api`, `fix/source-timeout`, `docs/api-contract`, or `chore/agent-guidelines`.
4. Start from the integration branch when one exists and can be identified. Check the Git configuration rather than assuming it is named `main`. If the work depends on an unmerged branch, start from that branch and explain the dependency. In a repository without commits, still create the dedicated branch before the first edits.
5. Reuse the dedicated branch when continuing the same task. Do not mix independent features on one branch.
6. Implement the requested scope, update relevant documentation, and run appropriate checks.
7. Review the diff, run `git diff --check`, and stage **the feature's files explicitly**. Review `git diff --cached` before committing. Avoid `git add .` and `git add -A` when they could include pre-existing work.
8. **Create a final commit at the end of every completed feature**, without waiting for another user request. Multiple coherent commits are acceptable when warranted; do not leave the feature's changes uncommitted.
9. Use a precise **English** message in the form `<type>(<scope>): <action and outcome>`. Types: `feat`, `fix`, `docs`, `refactor`, `test`, and `chore`. Example: `feat(worker): ingest all six series with idempotent backfill`. Use the imperative mood. Avoid vague final messages such as `update`, `changes`, or `WIP`. Add an English body when context or limitations need explanation.
10. After committing, check the Git status and report the branch, commit hash, message, checks performed, and any remaining pre-existing changes.

Do not develop directly on the integration branch. Do not merge, push, publish, rewrite history, or force-push without a corresponding request. Do not bypass hooks, invent a Git identity, or ignore a failed commit; report the issue if the commit cannot be created.

Keep personal specifications, financial planning, and one-off API investigation reports and captures **local and uncommitted**, unless the user explicitly requests their publication. Use local Git exclusions for these working materials. Commit useful project source, contributor documentation, and relevant tests; sanitized fixtures needed by automated tests may be included. Review staged paths and contents for private material before every commit.

## MVP architecture

- Backend: Python and FastAPI; database: PostgreSQL; frontend: plain HTML and JavaScript; startup: Docker Compose.
- Keep responsibilities clear across source access, persistence, the worker, API endpoints, and presentation.
- Add a dependency only for a concrete need. Do not introduce Redis, TimescaleDB, or a frontend framework for the MVP without a requested scope change.
- Document actual commands as tooling is added. Do not report nonexistent commands or tests as executed.
- Keep secrets out of the repository. Provide required settings in an example configuration without sensitive values. Document migrations and startup commands when those components are added.

## Container-only development

- Docker Engine with Docker Compose v2 is the only required local runtime. Do not require a local Python, PostgreSQL, Node.js, package manager, or virtual environment.
- Keep `docker compose up --build` sufficient to start the implemented application from a fresh checkout. Provide working local defaults; `.env` customization must remain optional.
- Run application checks and tests inside Docker. Keep the Makefile an optional convenience and document equivalent Docker Compose commands, including commands usable from PowerShell.
- Keep tests isolated from the development database and independent of public API availability. Preserve database volumes during routine shutdown.
- Keep local planning notes, investigation captures, credentials, and `.git` out of Docker build contexts as well as commits.

## Data and ingestion

- Primary source: `https://api.existenz.ch/apiv1/hydro`. Include `app=rhone-arve-guru` and the application version in requests.
- Confirmed series: Rhône **2606** (`flow`, `temperature`); Arve **2170** (`flow`, `temperature`, `height`, `turbidity`). Do not assume every station provides every parameter.
- Store the source station code, parameter, measurement timestamp, and value. Use timezone-aware dates and store instants in UTC with `timestamptz`.
- Enforce idempotency using the `(station_id, parameter, ts)` key and `INSERT ... ON CONFLICT DO NOTHING`.
- Ingest every 10 minutes, use bounded network timeouts, and handle errors so the worker can continue after source outages.
- Backfill missed measurements through `/daterange`, using explicit UTC bounds and an overlapping window. `/latest` alone cannot recover missed history.
- Validate responses before insertion. Never turn a missing or invalid measurement into zero; preserve gaps instead of fabricating observations.
- Track freshness **per station and parameter** because timestamps can differ. The source's global `/health` endpoint does not establish the freshness of all six series.
- `height` is a water-surface elevation, not water depth. The Existenz catalog labels `turbidity` as **BSTU**, while the FOEN station page uses **NTU**. Preserve source values and units; do not assume a conversion or equivalence.
- Preserve local investigation snapshots when checking the source again; date new captures or explicitly document their replacement. Do not commit these captures by default.

## API and interface

- Implement the specified routes: `GET /latest`, `GET /history?station=&param=&from=`, and `GET /health`.
- Validate input and bound history requests to prevent unlimited reads. Use parameterized SQL queries.
- Expose the units, measurement timestamps, and freshness needed to interpret the data correctly. Distinguish worker health from data health.
- Build a mobile-readable page with current values, a 24-hour chart, and explicit missing-data, stale-data, and error states.
- Credit and link to FOEN, and reference Existenz. Do not assume non-commercial usage terms permit monetization.

## Security

- Treat every value from the Existenz API as untrusted input. Validate type, range, station, and parameter against an allowlist before insertion. Never render source values as HTML; use `textContent`, not `innerHTML`.
- Never log secrets, full connection strings, or raw request bodies. Error responses must not expose stack traces, SQL, or internal hostnames. `/health` reports status only.
- Keep the API read-only: no public endpoint writes to the database. Restrict CORS to the origins that need it; no wildcard once publicly deployed.
- Containers run as non-root, without `privileged` mode or extra capabilities, with no published database port. Pin image versions.
- Do not weaken the Security workflow: no `pull_request_target`, no write permissions, no ignore rules for an active secret. When dependencies change, keep `requirements-lock.txt` complete so the audit stays valid.
- Before the final commit of any change touching API routes, Dockerfiles, Compose files, workflows, or deployment configuration, run the `security-engineer` subagent on the diff. Report its findings and how each was handled. The subagent never edits files.

## Indices and wording

- Current and contrast thresholds are indicative, unofficial, and still need calibration. Do not invent thresholds or present provisional values as validated.
- Resolve the BSTU/NTU discrepancy before calibrating the Jonction index. The relationship between measured turbidity and visual contrast also requires validation.
- Display the specified warning: the application does not replace official guidance. No index may declare swimming permitted or guarantee safety.
- When data is insufficient or stale, mark the index unavailable instead of providing a reassuring default. Document the chosen freshness criterion when implementing it.

## Verification and definition of done

- Run checks appropriate to the change and any repository-required commands once tooling exists. For documentation-only changes, proofreading and a diff check are sufficient.
- For ingestion and persistence, verify repeated ingestion produces no duplicates, backfill works, partial or invalid data is handled, and processing recovers after source outages.
- For the API, check responses, invalid inputs, empty history, and freshness. Use a real PostgreSQL database for behavior that depends on PostgreSQL.
- For the interface, check mobile layouts, units, timestamps, and missing or stale data states.
- Automated tests must be reproducible and independent of public API availability. Reserve real network calls for explicit, bounded integration checks.
- Before declaring the MVP complete, verify startup with `docker compose up`, measure the `/latest` response-time target of less than 100 ms, and observe the worker for 24 hours. Do not claim these criteria are met based on shorter tests or estimates.
- A completed feature includes its implementation, useful documentation, relevant checks, and final commit on its dedicated branch. Report any criteria still awaiting verification.
- For security-relevant changes, a completed feature includes the `security-engineer` review and its reported outcome.