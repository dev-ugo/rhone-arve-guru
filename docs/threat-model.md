# Measurement API threat model

Reviewed on 2026-11-04 against feature commit `99f3768`, which adds `GET /latest`
and `GET /history`. This document formalizes the model **after implementation**,
following the initial focused threat analysis. It records the final controls and
verification evidence; it is not evidence that a full documented model existed
before coding.

The method follows the decomposition, threat identification, mitigation, and
validation approach in the [OWASP Threat Modeling Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Threat_Modeling_Cheat_Sheet.html),
using STRIDE as prompts for relevant scenarios. The source was consulted on
2026-11-04. Priorities below reflect prerequisites and consequences in this
application, rather than numerical risk scores.

## Scope and deployment assumptions

The reviewed change exposes stored hydrological observations through two public
read routes in [app/measurements.py](../app/measurements.py). The [API contract](api.md)
defines validation, response fields, errors, units, and freshness. Existing
ingestion and `/health` are context for this model, not a new exhaustive audit of
the worker, containers, CI, or dependencies.

The implemented deployment is local Docker Compose:

- [compose.yaml](../compose.yaml) publishes the API on host loopback
  `127.0.0.1`; PostgreSQL has no published host port.
- API, worker, and migrations share the configured PostgreSQL identity. Compose
  does not define a separate API role with restricted grants.
- The application container uses the non-root application user defined in the
  [Dockerfile](../Dockerfile). Container and host administration remain trusted.
- There are no accounts, sessions, tenants, private user records, or public write
  operations. Anyone able to reach the API is intentionally allowed to read the
  same public observations.
- API reads do not call Existenz, initiate ingestion, or accept a target URL.
  They do not give callers an outbound request capability.

Internet hosting, a reverse proxy, TLS termination, request-rate enforcement,
production database roles, and the provider's network controls are **not
implemented or verified by this feature**. Local exposure limits which attackers
can reach the routes; it does not make HTTP inputs trustworthy. No production
security or load-capacity conclusion follows from this review.

## Assets and actors

The protected assets are API/database availability, the integrity of stored
measurements and their timestamps, correct communication of uncertainty and units,
database credentials, and the separation between application processes and the
host. Measurement values are public; credentials and internal exception details
are not. Misleading an API consumer about freshness or a swimming indicator can
matter even when no confidential data is involved.

| Actor | Legitimate access or attacker prerequisite | Relevant capability |
| --- | --- | --- |
| Reader or future dashboard | Reachable HTTP API | Read public values and history; no identity or ownership boundary to cross |
| Maintainer | Trusted access to the checkout and Docker host | Configure credentials, run migrations and services, inspect data |
| Untrusted HTTP client | Currently requires access to the local listener; an Internet deployment would broaden reach | Supply arbitrary query strings, repeat requests, choose dense valid windows |
| Compromised upstream or upstream publisher | Ability to influence the response served by the configured Existenz source | Supply malformed observations, or false observations that satisfy structural checks |
| Compromised application process | Separate code-execution or credential compromise, not demonstrated by these routes | Use the shared database identity outside the intended route transaction |

## Data flow and trust boundaries

```mermaid
flowchart LR
    Reader["Reader or untrusted HTTP client"]
    Source["Existenz HTTPS source"]
    subgraph Host["Trusted local Docker host"]
        subgraph Network["Compose network"]
            API["API container: latest and history"]
            Worker["Existing adapter and worker"]
            DB[("PostgreSQL: observations and worker state")]
        end
    end
    Reader -->|"B1: HTTP via host loopback"| API
    API -->|"Public JSON values, units and freshness"| Reader
    Source -.->|"B2: untrusted HTTPS JSON, existing flow"| Worker
    Worker -.->|"B3: validated parameterized inserts, existing flow"| DB
    API -->|"B3: bound SQL in read-only transactions"| DB
    DB -->|"Stored observations"| API
```

**B1: caller to API.** Query values cross from an untrusted client into parsing,
range checks, SQL arguments, and JSON serialization. Lack of authentication is
intentional for these public reads. Absence of cross-origin middleware is not
authentication or protection against direct HTTP requests.

**B2: source to ingestion.** HTTPS transport does not establish the truth of a
measurement. The existing [adapter](../app/source.py) checks envelope structure,
station/parameter identity, numeric and finite values, and timestamp bounds. It
also bounds response size; the [worker](../app/worker.py) uses network timeouts
and retries failed series on later cycles. There are no calibrated physical
plausibility thresholds or independent observation-authenticity checks.

**B3: processes to database.** Parameterized queries and database constraints
protect intended operations. The API explicitly starts read-only transactions,
but the processes share a database identity. That identity is not a least-privilege
boundary between API, ingestion, and migrations. PostgreSQL's unexposed host port
does not prevent access by a compromised authorized process on the Compose network.

## Threats, priorities, and responses

The date-conversion defect below was confirmed and corrected during feature
verification. The other scenarios describe plausible abuse paths and residual
architectural risks; they are not claims of demonstrated exploitation. Evidence
IDs refer to the verification inventory in the next section.

| Asset / flow | Scenario and prerequisites | Existing controls | Likelihood, impact, priority | Control added by the feature | Effective verification | Residual risk / assumption |
| --- | --- | --- | --- | --- | --- | --- |
| T1: history input parsing; denial of service | A reachable caller sends an aware timestamp whose UTC conversion exceeds Python's representable date range | Datetime parsing and the intended 30-day bound | Easy input to construct; an uncaught exception caused a request failure. Correct before delivery | Validate the allowed interval before converting to UTC | E1: both extreme dates return 422; E2 includes live HTTP checks | Fixed in this feature. A sustained outage or process crash was not demonstrated |
| T2: SQL access; tampering and disclosure | A caller injects SQL into station, parameter, or date values, or attempts a write method | Database station/parameter and finite-value constraints | Inputs are attacker-controlled; successful injection could expose or alter data. Essential route constraint | Station/parameter allowlist, aware date validation, bound SQL arguments, GET-only routes, read-only transactions | E1: malicious inputs rejected before connection; write methods return 405; code inspection confirms binding and transaction mode | No injection identified. Transaction mode does not restrict a compromised process using a new connection; API-only grants remain a deployment concern |
| T3: per-request database and response work; denial of service | A caller requests very old history or a dense valid series | Composite primary key; existing 3-second connection and 5-second statement timeouts | Straightforward without bounds; potentially excessive database and response work. Essential route constraint | Last 30 days only; SQL returns at most 5,001 rows and rejects more than 5,000 points; latest performs six lateral lookups with `LIMIT 1` | E1: exact time bounds, 5,000/5,001 cap and ordering; E2/E3: live reads and bounded latency sample | Result caps do not bound every internal database operation or total concurrent work. Connection and query timeouts are not an overall HTTP deadline |
| T4: shared service capacity; denial of service | A reachable client floods otherwise valid requests, opening repeated database connections | Localhost publication limits current reach | Exploit threshold unmeasured; sustained traffic could deny service. Review before Internet exposure | Per-request controls from T3 reduce work, but no flood-specific control was added | E3 covers sequential requests only; no concurrent flood test | No request-rate limit or proven concurrent-capacity budget. Public ingress and connection/concurrency limits require deployment decisions |
| T5: internal information in failures; disclosure | A client makes requests while the database or measurement schema is unavailable | Existing bounded database connection handling | Database outages are plausible; uncensored exceptions could reveal internals. Required failure behavior | Catch PostgreSQL errors and return a fixed generic 503, without logging the exception or connection details in the new routes | E1: refused database connection, exact generic body, then recovery | Tests cover connection failure; not every database failure mode or future proxy/error handler. No claim that arbitrary exceptions are globally sanitized |
| T6: upstream observations; tampering or source spoofing | An attacker controls the upstream response, or an upstream defect supplies false but structurally valid values | Fixed HTTPS source, validation of types/finite values/series/time window, database constraints and idempotency | Requires upstream influence; could corrupt the public interpretation of real conditions. Preserve source uncertainty; review when adding sources or indices | API retains source units, timestamps and explicit missing/stale states; reads do not introduce another source path | E1 tests presentation; E4 exercises malformed upstream data, finite checks and retry behavior with mocked HTTP | A plausible finite value is not verified as physically correct. No independent source comparison or calibrated physical range check; HTTPS does not resolve this |
| T7: interpretation of conditions; business-logic misuse | A reader or downstream consumer treats absent/stale values, turbidity units, or provisional indices as reassurance about swimming | Six known series and original catalog units; existing independent health signals | Misinterpretation is plausible and can have serious consequences. Required product constraint before exposing indices | Missing observations remain null; stale/future values are marked; freshness is per series; both indices remain unavailable with reasons and an explicit warning | E1: zero versus missing, independent timestamps, freshness boundaries, future values, unavailable indices and warning | Clients may ignore metadata. Thirty minutes is operational, not a safety threshold; BSTU/NTU, visual contrast and calibration remain unresolved |

### Confirmed defect: extreme timezone conversion

Initially, history normalized the parsed date to UTC before checking the allowed
interval. Inputs such as `0001-01-01T00:00:00+01:00` and
`9999-12-31T23:59:59-01:00` can exceed the datetime representation during that
conversion. The final implementation checks the allowed range first, rejecting
these requests with 422 before database access. Regression inputs are in
`test_history_rejects_invalid_inputs_before_accessing_database`.

This is a corrected input-handling vulnerability, distinct from the untested
possibility of sustained resource exhaustion. No claim is made that those inputs
could crash the worker, corrupt data, or provide code execution.

## Verification inventory and limits

These are results already obtained during the feature's implementation on
2026-11-04 and reused for this model. Writing this document did not rerun them.
Code and test mappings were reviewed against `99f3768`.

| Evidence | Recorded result and reproducible source | What it establishes / limit |
| --- | --- | --- |
| E1: deterministic application suite | 100 passing tests with real isolated PostgreSQL in Docker, plus Ruff lint and formatting checks. Includes 52 cases in [tests/test_measurements.py](../tests/test_measurements.py) | Route behavior, input boundaries, original units, missing and stale states, caps, generic DB failure/recovery, GET-only methods, and schema. HTTP requests use ASGI transport; this is not a public load test |
| E2: live server smoke checks | Uvicorn with migrations and PostgreSQL, without worker/public-source requests: empty results, extreme dates returning 422, and a 24-hour request returning 144 synthetic points | The read paths also work through a live HTTP server with empty and populated storage; not a complete deployment or ingestion observation |
| E3: local latency sample | 25,920 synthetic rows, six series, 30 days at ten-minute intervals; 100 sequential requests after 10 warmups: median 6.617 ms, p95 7.785 ms, maximum 10.109 ms | Sample for the less-than-100-ms `/latest` target only in that environment. Persistent client and Uvicorn loopback inside the API container, separate PostgreSQL container; no concurrency, Internet latency, or production sizing proof. Details in [api.md](api.md#verification) |
| E4: existing ingestion and health tests in E1 | [tests/test_source.py](../tests/test_source.py), [tests/test_worker.py](../tests/test_worker.py), [tests/test_persistence.py](../tests/test_persistence.py), and [tests/test_health.py](../tests/test_health.py) | Mocked upstream rejection, bounds, idempotency, backfill, outage recovery and independent freshness. No public source truth validation or continuous 24-hour run |
| E5: existing scanner runs | Bandit: zero findings; pip-audit: no known vulnerabilities reported for the audited packages; Gitleaks: no leaks reported across 10 commits | Supporting evidence for their specific rule sets, dependency inventory, advisory state, and scanned Git history. They do not validate business logic, operating-system packages, runtime privilege isolation, or absence of all secrets |

The regular suite command is documented in [api.md](api.md#verification) and uses
[compose.test.yaml](../compose.test.yaml). Scanner commands and coverage are in
the [README](../README.md#security-checks). No dependency or workflow change was
needed for the API feature. Scanner results are not substitutes for this model
or the independent security review required by the repository.

The GET-only tests establish that public write methods are rejected and leave
measurements unchanged. Read-only SQL transaction mode was verified by inspecting
the route code, not by a dedicated test of database-role grants. Internet
transport security, request floods, production database permissions, and a
continuous 24-hour worker observation remain unverified.

## Design decisions and alternatives

- Keeping reads separate from ingestion avoids making source outages or network
  responses part of a caller's synchronous request. The trade-off is explicit
  freshness metadata rather than an assumption of live data.
- A fixed window and row cap are sufficient for the MVP chart contract. The API
  rejects dense overflow explicitly instead of silently truncating or adding
  pagination/aggregation with new semantics. Revisit that decision if actual
  source cadence prevents useful windows.
- Bound SQL arguments prevent input from becoming SQL structure. Read-only
  transactions add protection for intended statements. A separately granted API
  database role would contain a compromised process more effectively; the shared
  local identity does not provide that control.
- A future ingress proxy could enforce request rates and concurrent work without
  adding another application service. Application-level limits are another
  option. Neither is implemented or proven here; a choice needs deployment and
  measured traffic context. Adding Redis or caching is not required by this model.
- Withholding the indices avoids manufacturing calibrated meaning from available
  values. Turning them on requires validated units and thresholds, not merely
  fresh input. No index may establish swimming permission or guarantee safety.

Repudiation and cross-user authorization were considered: there is no
state-changing user workflow, account identity, or private per-user resource in
this feature. No artificial account or audit-log requirement is added. New
identity, ownership, or write operations would change that conclusion.

## Revisit criteria and follow-up ownership

Before Internet exposure, the maintainer and deployment/security reviewer should
update this model for the actual provider and ingress. Confirm TLS termination,
network reachability, required origins, production credentials and separated
database permissions; select and verify request-rate/concurrency controls and
failure observability without sensitive logging. Test expected concurrent traffic
and failure behavior in that environment. These are review criteria, not changes
implemented or an approval granted by this feature.

Revisit B1/T2/T4/T5 if authentication, private data, cross-origin clients, or write
routes are introduced. Revisit B2/T6 when source URLs, adapter validation, source
cadence, or retention change. When building the dashboard, revisit T7 to preserve
safe rendering, units, timestamps and freshness metadata, and keep the indices
explicitly unavailable. Building that dashboard does not require calibrated
indices. Before activating an index, resolve its unit questions, validate the
relationship to the claimed phenomenon, and calibrate thresholds with appropriate
domain evidence; Jonction specifically requires resolving BSTU/NTU and validating
visual contrast.

The maintainer still needs the MVP's 24-hour worker observation. Future changes
to Docker privileges, database identities, ingress, or dependency/workflow policy
also require a fresh review of the affected boundaries. The current evidence
supports the scoped local read API; it does not establish that the entire project
is secure or ready for production.

## Mobile dashboard assessment — 2026-11-04

### Pre-implementation scope and design constraints

This assessment was recorded before implementing the dashboard. It extends the
existing API model rather than replacing its historical evidence. The planned
feature serves a French, mobile-readable HTML page at `/`, with local CSS and
JavaScript under `app/static`, through the existing FastAPI process. The page
reads `/latest` and bounded `/history` requests for six confirmed series, shows
their source units, measurement times and freshness, and draws a selectable
24-hour SVG chart. It introduces no account, write route, public deployment,
runtime dependency, external script, font, analytics service, or direct browser
request to Existenz. Current and Jonction indices remain unavailable.

The affected assets are browser execution integrity, availability of the existing
read API, and accurate communication of observations and uncertainty. Existing
database credentials and host isolation remain relevant but gain no new intended
browser capability. Actors are public readers, a reachable malicious HTTP
client, an upstream publisher able to influence stored values, and the trusted
maintainer controlling static files. There is no new identity or tenant boundary.

The added flow is `browser -> same-origin HTML/CSS/JS -> /latest or /history ->
existing read-only database queries -> JSON -> DOM/SVG`. Browser DOM construction
is a new trust boundary: a JSON value is data, never markup, an executable URL,
or a script. The existing B2 upstream and B3 database boundaries still apply.
Serving static files must expose only the dedicated asset directory, not the
checkout, local planning notes, credentials, or database configuration.

The following table was first recorded with planned mitigations and checks. It
was updated after implementation on the same date to distinguish inspected
controls, executed verification, and remaining work.

| Asset / flow | Threat scenario and prerequisite | Existing controls | Likelihood / impact and priority | Implemented mitigation | Verification evidence | Residual risk / open assumption |
| --- | --- | --- | --- | --- | --- | --- |
| D1: JSON to DOM/SVG | A malformed or compromised response supplies markup or nonnumeric chart input | Adapter/API validation and six-series allowlist | Requires response influence; script execution or misleading output would be material. Required rendering constraint | DOM text nodes/`textContent`; SVG namespace with locally constructed attributes; allowlisted labels and units; finite numeric and chart-range checks; same-origin CSP without inline script or evaluation | M1 checks response headers; M2 rejects markup in numeric fields, unexpected units, unknown/duplicate series and numeric overflow; M4 inspects DOM sinks. No browser injection-execution test is claimed | CSP is defense in depth and does not establish source authenticity |
| D2: latest values and chart interpretation | Old browser state, missing points, mismatched units, or an index placeholder is interpreted as current or safe | API freshness per series, explicit nulls and unavailable indices | Source gaps and outages are normal; misleading reassurance can have serious consequences. Required product constraint | Original units and individual dates; null remains absent and zero stays numeric; freshness recomputed from API time plus monotonic elapsed time; separate gap segments; indices unconditionally unavailable; explicit French warning | M2 covers missing/zero, tiny nonzero formatting, expiry/future dates, gaps and malicious index fields; M3 confirms empty/fresh/partial/stale synthetic states, six source units, zero BSTU, individual dates, chart gap, unavailable indices, cached-value behavior during database failure, initial failure and manual recovery | Thirty minutes remains operational, not a safety threshold; BSTU/NTU, visual contrast and calibration remain unresolved |
| D3: browser refresh and history requests | Repeated interactions or late responses cause excessive requests or replace the selected series with older results | API window/row limits and bounded database operations | Normal interactions can trigger races; direct request floods remain possible. Bound the new client behavior | Eight-second abort timer; guarded 60-second latest refresh; abort and sequence checks for history; hidden-tab cancellation; one selected 24-hour series; failed/changed history clears its previous curve; explicit manual retry | M2 verifies selected-series identity and bounded ordered points; M4 inspects scheduling, cancellation and sequence checks. Slow-response, timeout and request-race behavior has not been exercised | Browser throttling is not a server rate limit; the one-million-character body check occurs after reading, so it is not a streaming memory cap. The existing fixed API response cap remains relevant; T4 remains open before Internet exposure |
| D4: static serving and browser policy | An attacker requests paths outside the asset directory, embeds the dashboard, or induces external script loading | Narrow Docker build context, non-root application user, localhost publication | Reachable path requests are easy; disclosure or browser compromise would be material. Required serving constraint | Dedicated static mount; CSP, `nosniff`, framing denial, no referrer and no-store on dashboard/successful asset responses; existing Swagger behavior preserved | M1 checks served MIME types/headers, rejected traversal/repository paths, database failure and `/docs`; M4 inspects Docker copies and read-only dev mount. The optional Node model-test container has no network, a non-root user, read-only filesystem/mounts and dropped capabilities | No TLS, ingress hardening, public deployment or broader container audit is added. Browser policies do not uniformly cover API/docs or failed static requests |

The same-origin design needs no added CORS access and no new service. A custom
SVG chart avoids a CDN or chart-library supply chain; its numeric inputs and gap
handling have focused model tests. Height is identified as water-surface
elevation in the page's source explanation, and turbidity remains BSTU without
an assumed NTU conversion. A graph gap criterion describes display continuity
only, not evidence of a measured intermediate value or a hydrological safety
threshold.

### Verification inventory and remaining work

The following executed results were reported by the implementing agent on
2026-11-04; this documentation review inspected the implementation and tests but
did not independently rerun their containers. Existing API evidence E1-E5 above
remains historical and is not represented as a new scanner run.

| Evidence | Result and reproducible source | What it establishes / limit |
| --- | --- | --- |
| M1: Python application and asset suite | 110 passing tests with isolated real PostgreSQL in Docker, plus passing Ruff lint and formatting. Command: `docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests`; dashboard additions are in [tests/test_dashboard.py](../tests/test_dashboard.py) | Adds HTTP asset/MIME/policy checks, protected static-file scope, database-independent HTML and docs compatibility to the existing suite. ASGI requests do not execute JavaScript |
| M2: frontend model suite | 28 passing Node built-in tests in the final rerun. Command: `docker compose -f compose.frontend-test.yaml run --rm frontend-tests`; [test source](../tests/frontend/dashboard.test.mjs) | Validates pure data/freshness/segmentation/scaling behavior, tiny nonzero formatting and extreme tick calculations with no network or package installation; does not execute DOM code, timers, fetch races or browser layouts |
| M3: local browser inspection | Isolated tmpfs PostgreSQL project without a worker or public source; empty/fresh data, source units, zero BSTU, independent dates, visible gap and unavailable indices observed. All six selector choices produced the correct title/unit; the table had 144 rows at observation and retained the final zero. No document horizontal overflow at 320, 375, 768 and 1280 px; responsive SVG viewBox was `0 0 290 230` at 375 px. Partial data showed four fresh, one stale and one missing series; all-stale data retained six stale cards and stale chart status. Pausing only the disposable database retained cached values/dates/stale states, displayed explicit refresh failure and hid the failed chart. First load during that outage served HTML with six em dashes and explicit unavailable values/history. After unpausing and reseeding fresh synthetic data, manual refresh recovered six fresh readings and a 138-point Rhône-temperature chart with two segments | Evidence for these states, interactions and widths; not an exhaustive accessibility or browser compatibility audit. The desktop screenshot was kept outside the repository; no public source was contacted |
| M4: scoped implementation/configuration inspection | Reviewed [app/main.py](../app/main.py), `app/static`, [compose.frontend-test.yaml](../compose.frontend-test.yaml), dashboard tests and existing Docker/development mounts. Normal, development, test and frontend Compose configuration validation passed according to the implementing agent | Confirms intended code paths and container boundaries; code presence does not prove every runtime or timing behavior |
| M5: scoped scanner reruns | Bandit reported zero findings in Docker for the final implementation. `docker compose -f compose.security.yaml run --build --rm --no-deps dependencies` completed successfully; pip-audit reported no known vulnerabilities for both the locked application/test packages and the installed security tools' dependencies | Results cover Bandit's Python rules and pip-audit's packages/advisory state at execution. Gitleaks runs against committed history after the feature commit, with its result reported in the feature handoff; no new JavaScript scanner or operating-system image audit is claimed |
| M6: independent security review | The read-only reviewer identified one low-severity extreme tick-overflow issue. The implementation corrected it and added regression coverage; the reviewer inspected the correction and reported zero open critical/high/medium/low findings and acceptance for the examined local scope | Independent code review, not a production security guarantee. The reviewer did not independently rerun the tests |

### Confirmed correction: extreme chart tick overflow

The initial chart derived axis ticks with `span * index / 4`. A finite accepted
range could overflow at the multiplication before division, producing infinite
ticks and coordinates. The corrected [chart model](../app/static/dashboard-model.mjs)
uses `span * fraction` with fractions from zero through one. Regression tests
cover `[0, 1e308]` and `[-1e308, 0]`, requiring every tick and normalized position
to remain finite. This low-severity rendering defect was corrected before the
feature commit; no script execution, stored-data corruption or process compromise
was demonstrated.

The dashboard checks recorded above are complete for the requested local scope.
Slow-response races, timeouts and hidden-tab transitions have code-level controls
but no executed timing/visibility automation recorded here. Browser inspection
does not constitute a full accessibility or cross-browser audit.
The MVP's continuous 24-hour worker observation remains a separate unfulfilled
criterion; neither the synthetic browser checks nor the existing local latency
sample satisfies it. Public ingress capacity, TLS and database-role isolation
remain the earlier deployment follow-up; this dashboard does not resolve them.
