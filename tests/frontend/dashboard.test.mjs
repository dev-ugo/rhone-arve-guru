import { test } from "node:test";
import assert from "node:assert/strict";
import {
  SERIES,
  DAY_MS,
  FRESHNESS_MS,
  formatValue,
  keyOf,
  freshness,
  validateLatest,
  validateHistory,
  segments,
  chartScale,
  chartTicks,
} from "../../app/static/dashboard-model.mjs";

const now = Date.parse("2026-11-04T12:00:00Z");
const iso = (timestamp) => new Date(timestamp).toISOString();

test("numeric formatting preserves tiny nonzero readings and bounds extreme text", () => {
  assert.equal(formatValue(0), "0");
  assert.notEqual(formatValue(0.000001), "0");
  assert.ok(formatValue(Number.MAX_VALUE).length < 20);
  assert.ok(formatValue(-Number.MAX_VALUE).length < 20);
});
function latest() {
  return {
    generated_at: iso(now),
    series: SERIES.map((series) => ({
      station_id: series.station,
      parameter: series.parameter,
      unit: series.unit,
      value: 0,
      ts: iso(now),
      status: "fresh",
    })),
  };
}
function history() {
  return {
    station_id: 2606,
    parameter: "temperature",
    unit: "°C",
    from: iso(now - DAY_MS),
    to: iso(now),
    points: [
      { ts: iso(now - 3600000), value: 0 },
      { ts: iso(now), value: 12.5 },
    ],
  };
}

test("zero remains a measurement and missing readings retain a null timestamp", () => {
  const payload = latest();
  payload.series[1] = {
    ...payload.series[1],
    value: null,
    ts: null,
    status: "missing",
  };
  const result = validateLatest(payload);
  assert.equal(result.readings.get(keyOf(SERIES[0])).value, 0);
  assert.equal(result.readings.get(keyOf(SERIES[1])).timestamp, null);
});

test("freshness expires independently and future readings are never recent", () => {
  assert.equal(freshness(null, now), "missing");
  assert.equal(freshness(now - FRESHNESS_MS, now), "fresh");
  assert.equal(freshness(now - FRESHNESS_MS - 1, now), "stale");
  assert.equal(freshness(now + 1, now), "stale");
  assert.equal(freshness(now, now + FRESHNESS_MS + 1), "stale");
});

for (const [label, mutate] of [
  [
    "HTML in a numeric value",
    (body) => {
      body.series[0].value = '<img src=x onerror="alert(1)">';
    },
  ],
  [
    "numeric strings",
    (body) => {
      body.series[0].value = "0";
    },
  ],
  [
    "nonfinite values",
    (body) => {
      body.series[0].value = Infinity;
    },
  ],
  [
    "duplicate series",
    (body) => {
      body.series[0] = body.series[1];
    },
  ],
  [
    "unknown station",
    (body) => {
      body.series[0].station_id = 9999;
    },
  ],
  [
    "substituted units",
    (body) => {
      body.series[5].unit = "NTU";
    },
  ],
  [
    "missing date for a number",
    (body) => {
      body.series[0].ts = null;
    },
  ],
  [
    "null value with a date",
    (body) => {
      body.series[0].value = null;
    },
  ],
  [
    "date without timezone",
    (body) => {
      body.generated_at = "2026-11-04T12:00:00";
    },
  ],
  [
    "incomplete series",
    (body) => {
      body.series.pop();
    },
  ],
]) {
  test(`latest rejects ${label}`, () => {
    const body = latest();
    mutate(body);
    assert.throws(() => validateLatest(body));
  });
}

test("source index scores and HTML labels cannot become presentation fields", () => {
  const body = latest();
  body.indices = { current: { status: "safe", score: 100 } };
  body.series[0].label = "<script>alert(1)</script>";
  const result = validateLatest(body);
  assert.equal(result.indices, undefined);
  assert.equal(result.readings.get(keyOf(SERIES[0])).label, undefined);
});

test("history accepts empty, single and zero-valued series without filling gaps", () => {
  const body = history();
  assert.equal(validateHistory(body, SERIES[0]).points[0].value, 0);
  body.points = [];
  assert.deepEqual(validateHistory(body, SERIES[0]).points, []);
  body.points = [{ ts: iso(now), value: 0 }];
  assert.equal(validateHistory(body, SERIES[0]).points.length, 1);
});

for (const [label, mutate] of [
  [
    "another selected series",
    (body) => {
      body.station_id = 2170;
    },
  ],
  [
    "wrong unit",
    (body) => {
      body.unit = "NTU";
    },
  ],
  [
    "unordered points",
    (body) => {
      body.points.reverse();
    },
  ],
  [
    "duplicate timestamps",
    (body) => {
      body.points[1].ts = body.points[0].ts;
    },
  ],
  [
    "out-of-window point",
    (body) => {
      body.points[0].ts = iso(now - DAY_MS - 1);
    },
  ],
  [
    "numeric strings",
    (body) => {
      body.points[0].value = "0";
    },
  ],
  [
    "null values",
    (body) => {
      body.points[0].value = null;
    },
  ],
  [
    "more than 5000 points",
    (body) => {
      body.points = Array(5001).fill(body.points[0]);
    },
  ],
  [
    "unbounded history",
    (body) => {
      body.from = iso(now - DAY_MS * 30);
    },
  ],
]) {
  test(`history rejects ${label}`, () => {
    const body = history();
    mutate(body);
    assert.throws(() => validateHistory(body, SERIES[0]));
  });
}

test("a gap of more than 30 minutes starts a new line and isolated points survive", () => {
  const points = [
    { timestamp: now - FRESHNESS_MS * 2 - 1, value: 0 },
    { timestamp: now - FRESHNESS_MS - 1, value: 2 },
    { timestamp: now, value: 4 },
  ];
  assert.deepEqual(
    segments(points).map((group) => group.length),
    [2, 1],
  );
  assert.equal(segments(points).flat().length, points.length);
  assert.deepEqual(segments([]), []);
});

test("constant or negative temperatures have finite chart bounds", () => {
  for (const value of [0, -5, 12.5]) {
    const scale = chartScale([{ value }]);
    assert.ok(Number.isFinite(scale.low) && scale.low < value);
    assert.ok(Number.isFinite(scale.high) && scale.high > value);
  }
});

test("extreme finite values cannot overflow into SVG coordinates", () => {
  assert.throws(() =>
    chartScale([{ value: -Number.MAX_VALUE }, { value: Number.MAX_VALUE }]),
  );
});

test("chart ticks remain finite for large accepted positive and negative ranges", () => {
  for (const values of [
    [0, 1e308],
    [-1e308, 0],
  ]) {
    const scale = chartScale(values.map((value) => ({ value })));
    const ticks = chartTicks(scale);
    assert.equal(ticks.length, 5);
    assert.ok(ticks.every(Number.isFinite));
    assert.ok(
      ticks.every((value) =>
        Number.isFinite((value - scale.low) / (scale.high - scale.low)),
      ),
    );
  }
});
