import {
  SERIES,
  DAY_MS,
  keyOf,
  displayUnit,
  formatValue,
  freshness,
  validateLatest,
  validateHistory,
  segments,
  chartScale,
  chartTicks,
} from "./dashboard-model.mjs";

const byId = (id) => document.getElementById(id);
const timeFormat = new Intl.DateTimeFormat("fr-CH", {
  timeZone: "Europe/Zurich",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});
const hourFormat = new Intl.DateTimeFormat("fr-CH", {
  timeZone: "Europe/Zurich",
  hour: "2-digit",
  minute: "2-digit",
});
const stateLabels = {
  fresh: "Mesure récente",
  stale: "Mesure ancienne",
  missing: "Aucune mesure",
};
const cards = new Map();
let latest = null;
let clock = null;
let latestError = false;
let latestBusy = false;
let latestController = null;
let historyController = null;
let historySequence = 0;
let historyData = null;
let chartWidth = 0;

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

for (const series of SERIES) {
  const card = node("div", "measurement");
  const label = node("h4", "measurement-label", series.label);
  const reading = node("p", "measurement-reading");
  const value = node("span", "measurement-value", "—");
  reading.append(
    value,
    node("span", "measurement-unit", displayUnit(series.unit)),
  );
  const time = node("time", "measurement-time", "En attente de données");
  const status = node("span", "measurement-status", "Chargement…");
  card.append(label, reading, time, status);
  byId(
    series.station === 2606 ? "rhone-measurements" : "arve-measurements",
  ).append(card);
  cards.set(keyOf(series), { card, value, time, status });
}

function serverNow() {
  // A monotonic elapsed time keeps cached observations ageing during source outages.
  return clock
    ? clock.timestamp + performance.now() - clock.observedAt
    : Date.now();
}

function setClock(timestamp) {
  clock = { timestamp, observedAt: performance.now() };
}

function renderLatest() {
  const states = new Map();
  for (const series of SERIES) {
    const key = keyOf(series);
    const item = latest?.readings.get(key);
    const status = freshness(item?.timestamp ?? null, serverNow());
    states.set(key, status);
    const elements = cards.get(key);
    elements.card.dataset.state = status;
    elements.value.textContent =
      item?.value === null || item === undefined
        ? "—"
        : formatValue(item.value);
    elements.status.textContent = stateLabels[status];
    if (item?.timestamp !== null && item?.timestamp !== undefined) {
      elements.time.dateTime = new Date(item.timestamp).toISOString();
      elements.time.textContent = timeFormat.format(item.timestamp);
      elements.time.title = `${new Date(item.timestamp).toISOString()} · heure de Genève affichée`;
    } else {
      elements.time.removeAttribute("datetime");
      elements.time.removeAttribute("title");
      elements.time.textContent = "Aucune date disponible";
    }
  }
  const values = [...states.values()];
  const statusBar = byId("status-bar");
  if (latestError) {
    statusBar.dataset.state = "error";
    byId("overall-status").textContent = latest
      ? "Actualisation impossible · dernières mesures reçues affichées"
      : "Mesures indisponibles · réessayez avec Actualiser";
  } else if (values.every((value) => value === "missing")) {
    statusBar.dataset.state = "missing";
    byId("overall-status").textContent =
      "Aucune mesure disponible pour le moment";
  } else if (values.every((value) => value === "fresh")) {
    statusBar.dataset.state = "fresh";
    byId("overall-status").textContent = "Les six séries sont récentes";
  } else {
    statusBar.dataset.state = "stale";
    byId("overall-status").textContent =
      "Certaines mesures sont anciennes ou absentes";
  }
  byId("updated-at").textContent = latest
    ? `Dernière réception : ${timeFormat.format(latest.generatedAt)} · Genève`
    : "Les mesures ne sont jamais remplacées par zéro";
  const currentStatus = states.get("2606:flow");
  byId("current-reason").textContent =
    currentStatus === "missing"
      ? "Le débit du Rhône manque. Les seuils de courant restent à calibrer."
      : currentStatus === "stale"
        ? "Le débit du Rhône est ancien. Les seuils de courant restent à calibrer."
        : "Les seuils de courant doivent encore être calibrés.";
  const jonctionStatus = states.get("2170:turbidity");
  const unitReason =
    "Les unités BSTU/NTU et le lien avec le contraste visuel restent à valider.";
  byId("jonction-reason").textContent =
    jonctionStatus === "missing"
      ? `La turbidité de l’Arve manque. ${unitReason}`
      : jonctionStatus === "stale"
        ? `La turbidité de l’Arve est ancienne. ${unitReason}`
        : unitReason;
}

async function fetchJson(path, controller) {
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(path, {
      signal: controller.signal,
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      headers: { Accept: "application/json" },
    });
    if (
      !response.ok ||
      !response.headers.get("content-type")?.includes("application/json")
    ) {
      throw new Error("Response unavailable");
    }
    const text = await response.text();
    if (text.length > 1000000) throw new Error("Response too large");
    return JSON.parse(text);
  } finally {
    clearTimeout(timeout);
  }
}

async function refresh() {
  if (latestBusy || document.hidden) return;
  latestBusy = true;
  const controller = new AbortController();
  latestController = controller;
  byId("refresh").disabled = true;
  byId("refresh").setAttribute("aria-busy", "true");
  try {
    const body = validateLatest(await fetchJson("/latest", controller));
    if (controller.signal.aborted || document.hidden) return;
    latest = body;
    setClock(body.generatedAt);
    latestError = false;
  } catch {
    if (document.hidden) return;
    latestError = true;
  } finally {
    latestBusy = false;
    byId("refresh").disabled = false;
    byId("refresh").removeAttribute("aria-busy");
  }
  renderLatest();
  await loadHistory();
}

function selectedSeries() {
  return SERIES.find((series) => keyOf(series) === byId("series-select").value);
}

function clearHistory() {
  historyData = null;
  byId("chart-container").hidden = true;
  byId("history-details").hidden = true;
  byId("history-table").replaceChildren();
}

async function loadHistory() {
  historyController?.abort();
  const sequence = ++historySequence;
  clearHistory();
  const series = selectedSeries();
  byId("chart-legend").textContent =
    `${series.river} · ${series.label} (${displayUnit(series.unit)})`;
  byId("chart-status").textContent = "Chargement de l’historique…";
  byId("chart-container").dataset.river =
    series.station === 2606 ? "rhone" : "arve";
  if (!clock) {
    byId("chart-status").textContent =
      "Historique indisponible : la réception des mesures a échoué. Réessayez avec Actualiser.";
    return;
  }
  const controller = new AbortController();
  historyController = controller;
  const query = new URLSearchParams({
    station: String(series.station),
    param: series.parameter,
    from: new Date(serverNow() - DAY_MS).toISOString(),
  });
  try {
    const data = validateHistory(
      await fetchJson(`/history?${query}`, controller),
      series,
    );
    if (
      sequence !== historySequence ||
      controller.signal.aborted ||
      document.hidden
    )
      return;
    setClock(data.end);
    historyData = { series, ...data };
    if (!data.points.length) {
      byId("chart-status").textContent =
        "Aucune mesure dans cette fenêtre de 24 heures. La courbe apparaîtra dès que des données seront disponibles.";
      return;
    }
    byId("chart-container").hidden = false;
    drawChart(historyData);
    updateHistoryStatus();
    byId("chart-container").hidden = false;
    byId("history-details").hidden = false;
    if (byId("history-details").open) renderTable();
  } catch {
    if (sequence !== historySequence || document.hidden) return;
    clearHistory();
    byId("chart-status").textContent =
      "Historique indisponible. Les mesures actuelles restent indépendantes du graphique. Réessayez avec Actualiser.";
  }
}

function svgNode(tag, attributes = {}, text) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes))
    element.setAttribute(key, String(value));
  if (text !== undefined) element.textContent = text;
  return element;
}

function updateHistoryStatus() {
  if (!historyData?.points.length) return;
  const { series, points } = historyData;
  const last = points.at(-1);
  const status = freshness(last.timestamp, serverNow());
  const groups = segments(points);
  byId("chart-status").textContent =
    `${points.length} mesure${points.length > 1 ? "s" : ""} · ${stateLabels[status]} au ${timeFormat.format(last.timestamp)}${groups.length > 1 ? ` · ${groups.length - 1} interruption(s)` : ""}`;
  byId("history-caption").textContent =
    `${series.river} · ${series.label}, heures de Genève`;
  byId("history-unit").textContent = `Valeur (${displayUnit(series.unit)})`;
}

function drawChart({ series, start, end, points }) {
  const svg = byId("history-chart");
  const width = Math.max(260, byId("chart-container").clientWidth);
  const height = width < 580 ? 230 : 280;
  chartWidth = width;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const scale = chartScale(points);
  const left = width < 580 ? 48 : 64;
  const right = width - 12;
  const bottom = height - 35;
  const x = (timestamp) =>
    left + ((timestamp - start) / Math.max(1, end - start)) * (right - left);
  const y = (value) =>
    bottom - ((value - scale.low) / (scale.high - scale.low)) * (bottom - 25);
  const title = svgNode(
    "title",
    { id: "chart-title" },
    `${series.river} · ${series.label}, dernières 24 heures`,
  );
  const description = svgNode(
    "desc",
    { id: "chart-description" },
    `${points.length} mesures en ${displayUnit(series.unit)}. Les interruptions de plus de 30 minutes sont visibles. Une table des mesures est disponible après le graphique.`,
  );
  svg.replaceChildren(title, description);
  for (const value of chartTicks(scale)) {
    const position = y(value);
    svg.append(
      svgNode("line", {
        x1: left,
        x2: right,
        y1: position,
        y2: position,
        class: "chart-grid",
      }),
    );
    svg.append(
      svgNode(
        "text",
        {
          x: left - 10,
          y: position + 4,
          "text-anchor": "end",
          class: "chart-axis",
        },
        formatValue(value),
      ),
    );
  }
  svg.append(
    svgNode(
      "text",
      { x: left, y: 13, class: "chart-axis" },
      displayUnit(series.unit),
    ),
  );
  const tickCount = width < 500 ? 4 : 6;
  for (let index = 0; index <= tickCount; index++) {
    const timestamp = start + ((end - start) * index) / tickCount;
    svg.append(
      svgNode(
        "text",
        {
          x: x(timestamp),
          y: height - 6,
          "text-anchor":
            index === 0 ? "start" : index === tickCount ? "end" : "middle",
          class: "chart-axis",
        },
        hourFormat.format(timestamp),
      ),
    );
  }
  for (const group of segments(points)) {
    const path = group
      .map(
        (point, index) =>
          `${index ? "L" : "M"}${x(point.timestamp).toFixed(2)},${y(point.value).toFixed(2)}`,
      )
      .join(" ");
    svg.append(svgNode("path", { d: path, class: "chart-path" }));
  }
  for (const point of points) {
    const dot = svgNode("circle", {
      cx: x(point.timestamp),
      cy: y(point.value),
      r: points.length === 1 ? 4 : 1.6,
      class: "chart-point",
    });
    dot.append(
      svgNode(
        "title",
        {},
        `${timeFormat.format(point.timestamp)} : ${formatValue(point.value)} ${displayUnit(series.unit)}`,
      ),
    );
    svg.append(dot);
  }
}

function renderTable() {
  if (!historyData || !byId("history-details").open) return;
  const fragment = document.createDocumentFragment();
  for (const point of historyData.points) {
    const row = node("tr");
    row.append(
      node("td", "", timeFormat.format(point.timestamp)),
      node("td", "", formatValue(point.value)),
    );
    fragment.append(row);
  }
  byId("history-table").replaceChildren(fragment);
}

byId("refresh").addEventListener("click", refresh);
byId("series-select").addEventListener("change", loadHistory);
byId("history-details").addEventListener("toggle", renderTable);
new ResizeObserver(() => {
  const container = byId("chart-container");
  if (
    historyData?.points.length &&
    !container.hidden &&
    container.clientWidth !== chartWidth
  ) {
    drawChart(historyData);
  }
}).observe(byId("chart-container"));
setInterval(() => {
  if (latest && !document.hidden) {
    renderLatest();
    updateHistoryStatus();
  }
}, 15000);
setInterval(refresh, 60000);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    latestController?.abort();
    historyController?.abort();
    historySequence++;
  } else {
    if (latest) renderLatest();
    refresh();
  }
});
refresh();
