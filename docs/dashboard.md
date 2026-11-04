# Mobile dashboard

The French-language dashboard is served at `GET /` by FastAPI. It uses plain
HTML, CSS, JavaScript modules, and an SVG chart from `app/static`, with no
frontend build, runtime package, external font, analytics, or CDN request.
The existing Docker image includes these files. `docker compose up --build`
starts the dashboard and the rest of the application; `.env` remains optional.

Open [the dashboard](http://localhost:8000/). API documentation remains at
`/docs`; `/latest`, `/history`, and `/health` keep their existing JSON contracts.
The former bootstrap JSON response at `/` is replaced by the dashboard HTML.
Static resources are limited to `/static`; the repository root is never mounted
as an HTTP file directory. The page can load even when PostgreSQL is unavailable.

## Measurements and interpretation

The two river panels show the six confirmed series. Each reading has its own
measurement date and freshness status; timestamps are displayed in
`Europe/Zurich`, including the date and local daylight-saving changes.
The API's UTC timestamps remain unchanged. Source units are retained; `m3/s`
is typeset as `m³/s`. Numbers use up to two decimal places; very small nonzero
or very large values use scientific notation to avoid rounding to zero or
overflowing a mobile card. Water-surface elevation is labelled as a surface elevation,
not a depth. Arve turbidity stays in BSTU; no NTU conversion is assumed.

An absent reading displays an em dash, never zero. An explicitly measured zero
is displayed as zero. A reading is recent only when its age is between zero and
30 minutes inclusive. Future-dated observations are old, never recent. This
matches the API's operational freshness rule and says nothing about swimming
safety. The freshness clock starts at the API response time and advances using
the browser's monotonic elapsed time, so cached readings continue ageing when
requests fail or the tab is left open.

Both indices remain unavailable regardless of any scores supplied in an API
response. Their explanations distinguish missing/old inputs from pending
calibration and the unresolved BSTU/NTU and visual-contrast questions. The page
always includes the warning that the application does not replace official
guidance and cannot determine whether swimming is permitted or safe. Source
links credit FOEN/OFEV and Existenz.

## History and refresh behavior

One selector offers exactly the six supported station/parameter combinations.
The default is Rhône temperature. A history request covers the previous 24 hours,
using the server-time reference obtained from `/latest`, and retains the API's
5,000-point cap. The chart covers the requested time window, not just the interval
between the first and last received points. A single observation is a visible dot.
Lines connect received observations only when they are at most 30 minutes apart;
longer gaps start a separate line. This is a chart-continuity rule, not a claim
that sampling is complete or a calibrated index. Values are never interpolated
into missing records. A collapsible table gives a textual alternative to the SVG.
The chart resizes to the available width and the table scrolls within its panel.

The page requests `/latest` and the selected history every 60 seconds while
visible. Each request has an eight-second timeout; there are no immediate retry
loops. `Actualiser` retries manually. Changing series aborts the preceding
history request and ignores its late result. Hidden tabs stop starting refreshes
and abort in-flight requests; returning to the tab refreshes the data. Freshness
labels are recomputed every 15 seconds while visible and on return to the tab.

If current readings fail to refresh, a visible error explains that the last
received observations remain displayed with their original dates; they continue
ageing. An initial failure shows no values. An empty history and a history request
failure have different messages. A failed or changed history clears its old
curve, so a previously selected series cannot masquerade as the new selection.

## Browser boundary

API responses are validated for the known station/parameter combinations,
original units, timestamps, finite numbers, and ordered bounded history. Labels
come from the local allowlist. Values enter text nodes using `textContent`; chart
elements use the SVG namespace and finite coordinates. No API content is
interpreted as HTML. Fetches use only fixed same-origin read paths, omit
credentials, reject redirects, bypass the cache, and do not contact Existenz.

Dashboard HTML and successful static responses use a CSP with a default deny
policy, same-origin scripts/styles/images/connections, no inline script/eval,
no framing, no form submissions, and no base-URL overrides. They also set
`nosniff`, `DENY` framing, `no-referrer`, and `no-store`. This policy is scoped to
the dashboard and its assets; the existing Swagger UI retains its own behavior.
No CORS, write endpoint, database privilege, dependency lock, or workflow changes
are required. Deployment assumptions remain those of the
[threat model](threat-model.md).

## Verification

Run the application suite and frontend model suite using only Docker:

```sh
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yaml down
docker compose -f compose.frontend-test.yaml run --rm frontend-tests
```

These commands also work in PowerShell. Application tests use a real isolated
PostgreSQL database; frontend tests use Node's built-in runner without package
installation or network access. Neither suite contacts Existenz. HTTP tests cover
asset types and security headers, the static-file boundary, database failure,
and compatibility with API documentation. Model tests cover missing versus zero,
age expiry and future timestamps, rejected payloads and units, selected-series
identity, chronology and bounds, gaps, and numeric overflow.

Browser checks additionally cover the six selector choices, the textual table,
mobile widths, empty/partial/stale data, and request failure and recovery. Model
tests do not themselves execute a browser or establish visual accessibility.
The separate continuous 24-hour worker observation remains outstanding.
