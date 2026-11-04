// The source's original units are validated; typography is applied separately.
export const SERIES = Object.freeze([
  {
    station: 2606,
    parameter: "temperature",
    label: "Température",
    river: "Rhône",
    unit: "°C",
  },
  {
    station: 2606,
    parameter: "flow",
    label: "Débit",
    river: "Rhône",
    unit: "m3/s",
  },
  {
    station: 2170,
    parameter: "temperature",
    label: "Température",
    river: "Arve",
    unit: "°C",
  },
  {
    station: 2170,
    parameter: "flow",
    label: "Débit",
    river: "Arve",
    unit: "m3/s",
  },
  {
    station: 2170,
    parameter: "height",
    label: "Cote de l’eau",
    river: "Arve",
    unit: "m",
  },
  {
    station: 2170,
    parameter: "turbidity",
    label: "Turbidité",
    river: "Arve",
    unit: "BSTU",
  },
]);
export const FRESHNESS_MS = 30 * 60 * 1000;
export const DAY_MS = 24 * 60 * 60 * 1000;
const numberFormat = new Intl.NumberFormat("fr-CH", {
  maximumFractionDigits: 2,
});
const scientificFormat = new Intl.NumberFormat("fr-CH", {
  notation: "scientific",
  maximumFractionDigits: 2,
});

export function formatValue(value) {
  const magnitude = Math.abs(value);
  return (
    magnitude >= 1000000 || (magnitude > 0 && magnitude < 0.01)
      ? scientificFormat
      : numberFormat
  ).format(value);
}
export const keyOf = (series) => `${series.station}:${series.parameter}`;
export const displayUnit = (unit) => (unit === "m3/s" ? "m³/s" : unit);

export function instant(value) {
  if (typeof value !== "string" || !/T.*(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) {
    throw new Error("Invalid timestamp");
  }
  const result = Date.parse(value);
  if (!Number.isFinite(result)) throw new Error("Invalid timestamp");
  return result;
}

export function freshness(timestamp, now) {
  if (timestamp === null) return "missing";
  return now >= timestamp && now - timestamp <= FRESHNESS_MS
    ? "fresh"
    : "stale";
}

export function validateLatest(body) {
  if (
    !body ||
    !Array.isArray(body.series) ||
    body.series.length !== SERIES.length
  ) {
    throw new Error("Invalid measurements");
  }
  const generatedAt = instant(body.generated_at);
  const readings = new Map();
  for (const item of body.series) {
    const series = SERIES.find(
      (s) => s.station === item?.station_id && s.parameter === item?.parameter,
    );
    if (!series || item.unit !== series.unit || readings.has(keyOf(series))) {
      throw new Error("Invalid series");
    }
    const missing = item.ts === null && item.value === null;
    if (
      !missing &&
      (typeof item.value !== "number" || !Number.isFinite(item.value))
    ) {
      throw new Error("Invalid value");
    }
    const timestamp = missing ? null : instant(item.ts);
    if (missing && item.status !== "missing")
      throw new Error("Invalid missing state");
    readings.set(keyOf(series), { timestamp, value: item.value });
  }
  // Both indices stay unavailable even if a future response contains a score.
  return { generatedAt, readings };
}

export function validateHistory(body, series) {
  if (
    !body ||
    body.station_id !== series.station ||
    body.parameter !== series.parameter ||
    body.unit !== series.unit ||
    !Array.isArray(body.points) ||
    body.points.length > 5000
  ) {
    throw new Error("Invalid history");
  }
  const start = instant(body.from);
  const end = instant(body.to);
  if (end < start || end - start > DAY_MS + 60000)
    throw new Error("Invalid history window");
  let previous = -Infinity;
  const points = body.points.map((point) => {
    const timestamp = instant(point?.ts);
    if (
      timestamp < start ||
      timestamp > end ||
      timestamp <= previous ||
      typeof point.value !== "number" ||
      !Number.isFinite(point.value)
    ) {
      throw new Error("Invalid history point");
    }
    previous = timestamp;
    return { timestamp, value: point.value };
  });
  return { start, end, points };
}

export function segments(points) {
  const groups = [];
  for (const point of points) {
    const group = groups.at(-1);
    if (!group || point.timestamp - group.at(-1).timestamp > FRESHNESS_MS)
      groups.push([point]);
    else group.push(point);
  }
  return groups;
}

export function chartScale(points) {
  const values = points.map((point) => point.value);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const padding = Math.max((high - low) * 0.12, Math.abs(high) * 0.005, 0.1);
  // Very large finite inputs must not generate Infinity in SVG coordinates.
  if (
    ![low - padding, high + padding, high - low + 2 * padding].every(
      Number.isFinite,
    )
  ) {
    throw new Error("Unrepresentable chart range");
  }
  return { low: low - padding, high: high + padding };
}

export function chartTicks(scale) {
  const span = scale.high - scale.low;
  return [0, 0.25, 0.5, 0.75, 1].map((fraction) => scale.low + span * fraction);
}
