# Measurement API

The API reads stored measurements; requests never contact Existenz or write
measurements. Interactive documentation and the generated schema are available
at `/docs` and `/openapi.json`. Start the application with:

```sh
docker compose up --build -d --wait
```

All timestamps represent UTC instants and include a timezone. Units preserve the
Existenz catalog: `flow` is `m3/s`, `temperature` is `°C`, `height` is `m`
(water-surface elevation, not depth), and `turbidity` is `BSTU`. The FOEN station
page uses NTU for turbidity; no conversion or equivalence is assumed.

| Station | Supported parameters |
| --- | --- |
| Rhône 2606 | `flow`, `temperature` |
| Arve 2170 | `flow`, `temperature`, `height`, `turbidity` |

## Latest measurements

`GET /latest` returns HTTP 200 even when stored measurements are absent or stale.

| Field | Meaning |
| --- | --- |
| `generated_at` | UTC time used to evaluate this response |
| `data` | `fresh` if all six series are fresh; `unavailable` if none has readings; otherwise `stale` |
| `series` | Six entries in the station/parameter allowlist, including missing series |
| `series[].station_id`, `parameter`, `unit` | Source station code, parameter, and catalog unit |
| `series[].ts`, `value` | Latest stored measurement, or both null when missing |
| `series[].status` | `fresh`, `stale`, or `missing`, independently for each series |
| `indices.current`, `indices.jonction` | Unavailable indicative indices, with explicit reasons |
| `warning` | The application does not replace official guidance or determine swimming permission or safety |

The most recent stored reading is selected independently for each series. A
reading is fresh when its timestamp is between `generated_at - 30 minutes` and
`generated_at`, inclusive. Older or future readings are stale. Thirty minutes
allows three nominal ingestion intervals; it is an operational criterion, not a
calibrated current threshold or safety assessment. Stale values remain visible
with their original timestamp; missing measurements are never replaced with zero.

Both indices always have `status: "unavailable"`. Current uses Rhône flow;
Jonction uses Arve turbidity. Their reasons are:

| Reason | Meaning |
| --- | --- |
| `data_missing` | The required series has no stored reading |
| `data_stale` | The required reading fails the freshness criterion |
| `calibration_pending` | Current thresholds have not been validated |
| `unit_validation_pending` | Jonction needs resolution of BSTU/NTU, validation of visual contrast, and calibration |

Data absence or staleness takes precedence over pending calibration. Fresh data
does not make either index available. No index indicates that swimming is
permitted or guarantees safety.

## History

`GET /history?station=&param=&from=` requires all three query parameters:

| Parameter | Validation |
| --- | --- |
| `station` | Integer station code from the table above |
| `param` | A supported parameter at that station |
| `from` | ISO 8601 timestamp with an explicit timezone, within the last 30 days and no later than the response time |

For example, `2026-11-04T08:00:00Z` and `2026-11-04T09:00:00+01:00` represent
the same instant. URL-encode a positive offset's plus sign as `%2B`; otherwise
query-string decoding treats it as a space. Naive dates and numeric Unix epochs
are not accepted.

The response contains `generated_at`, `station_id`, `parameter`, `unit`, `from`,
`to`, `status`, `latest_at`, and `points`. Bounds are normalized to UTC; `to`
equals `generated_at`. Each point contains `ts` and `value`, ordered from oldest
to newest in the inclusive interval `[from, to]`. Gaps are preserved without
interpolation or artificial observations. Empty history returns HTTP 200 with
`points: []`, `latest_at: null`, and `status: "missing"`.

`latest_at` is the newest point in the requested window. `status` applies the
same 30-minute freshness criterion to that point; it describes this window, not
all retained history. At most 5,000 points may be returned. The query reads at
most 5,001 points to detect overflow; a larger result produces HTTP 422 and the
caller must request a shorter interval. Results are never silently truncated.

The application retains ingested history, but the public route only reads the
last 30 days. It does not backfill on demand. A fresh installation initially
imports the last 24 hours; see [ingestion](ingestion.md) for recovery limits.

## Errors and health

| HTTP status | Meaning |
| --- | --- |
| 200 | Successful read, including absent or stale data |
| 422 | Missing/invalid input, unsupported station/parameter pair, invalid date range, or more than 5,000 history points |
| 503 | Database or measurement schema unavailable; `{"detail":"Measurements are temporarily unavailable"}` |
| 405 | An unsupported write method, such as POST to either measurement route |

Database failures return a generic message without SQL, connection details, or
stack traces. PostgreSQL connection and statement timeouts bound database work.
Queries use bound SQL parameters and the existing measurement primary key;
latest lookup retrieves one indexed reading for each expected series.

`GET /health` keeps infrastructure readiness separate from worker execution and
measurement freshness. See the [health contract](ingestion.md#health). Successful
measurement responses do not assert that the worker is healthy.

The API has no cross-origin middleware or public write routes. Compose binds it
to localhost. Public hosting will need an explicit deployment review, including
request-rate limits and the required origins; this feature does not deploy it.

## Try the routes

Open [interactive documentation](http://localhost:8000/docs), or use PowerShell:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/latest"
$historyFrom = [Uri]::EscapeDataString([DateTimeOffset]::UtcNow.AddHours(-24).ToString("o"))
Invoke-RestMethod -Uri "http://localhost:8000/history?station=2606&param=flow&from=$historyFrom"
```

A request can also run entirely inside the application container, in either
PowerShell or a POSIX shell:

```sh
docker compose exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/latest', timeout=8).read().decode())"
```

## Verification

Run lint, formatting, and deterministic API tests with isolated real PostgreSQL:

```sh
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yaml down
```

The tests cover independent latest readings and freshness, missing and zero
values, ordered and bounded history, timezone normalization, invalid input,
overflow, read-only methods, and database failure/recovery. They never contact
the public source or the development database.

The `/latest` target is less than 100 ms. On 2026-11-04, a local Docker Desktop
check with Python 3.13.18, PostgreSQL 17.11, and 25,920 synthetic measurements
(six series, 30 days at ten-minute intervals) measured 100 sequential HTTP
requests after ten warmups: median 6.617 ms, nearest-rank p95 7.785 ms, maximum
10.109 ms. Requests used a persistent HTTP client inside the API container against
Uvicorn on loopback, with PostgreSQL in a separate container. A 24-hour history
request returned 144 stored points from this synthetic dataset.

This sample is evidence only for that dataset, environment, and request count;
it does not establish public-hosting or concurrent-load performance, or the
required continuous 24-hour worker observation. The verification project ran the
API, migrations, and database without a worker or public source requests.
