"use strict";

const $ = (selector) => document.querySelector(selector);
const number = new Intl.NumberFormat("en", { maximumFractionDigits: 6 });
let scenarios = [];
let sample = null;
let result = null;
let revision = 0;
let views = new Map();
const timezone = () => $("#timezone").value;
const format = (value, options) =>
  new Intl.DateTimeFormat("en-GB", { timeZone: timezone(), ...options }).format(
    new Date(value),
  );
const clock = (value) => format(value, { hour: "2-digit", minute: "2-digit" });
const date = (value) =>
  format(value, { day: "numeric", month: "short", year: "numeric" });
const stamp = (value) =>
  format(value, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "shortOffset",
  });
const duration = (minutes) => `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
const validIntervals = () =>
  (sample?.intervals || []).filter(
    (r) =>
      Number.isFinite(Date.parse(r.start)) &&
      Number.isFinite(Date.parse(r.end)) &&
      Date.parse(r.end) > Date.parse(r.start) &&
      typeof r.price === "number" &&
      Number.isFinite(r.price),
  );

function invalidate() {
  revision++;
  result = null;
  $("#result").hidden = true;
  $("#error").hidden = true;
  $("#status").textContent =
    "Choose your running duration to find the best time.";
  $(".recommendation").setAttribute("aria-busy", "false");
  $("#calculate").disabled = !sample;
  drawChart();
}

function updateViews() {
  views = new Map();
  const intervals = validIntervals();
  $("#range").replaceChildren(new Option("All available", "all"));
  if (!intervals.length) return;
  const start = Math.min(...intervals.map((r) => Date.parse(r.start)));
  const end = Math.max(...intervals.map((r) => Date.parse(r.end)));
  // Daypart views are offered only for data covering a single displayed date.
  if (date(start) !== date(end - 1)) return;
  const localClock = new Intl.DateTimeFormat("en-GB", {
    timeZone: timezone(),
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  for (const [key, label, from, to] of [
    ["morning", "Morning · 06–12", 6, 12],
    ["afternoon", "Afternoon · 12–18", 12, 18],
    ["evening", "Evening · 18–24", 18, 24],
  ]) {
    for (let time = start; time < end; time += 60 * 1000) {
      const parts = localClock.formatToParts(new Date(time));
      const hour = Number(parts.find((p) => p.type === "hour").value);
      const minute = Number(parts.find((p) => p.type === "minute").value);
      const second = Number(parts.find((p) => p.type === "second").value);
      if (hour >= from && hour < to) {
        const lower =
          time -
          ((hour - from) * 60 + minute) * 60000 -
          second * 1000 -
          (time % 1000);
        const upper = lower + (to - from) * 3600000;
        if (
          intervals.some(
            (r) => Date.parse(r.start) < upper && Date.parse(r.end) > lower,
          )
        ) {
          views.set(key, [Math.max(start, lower), Math.min(end, upper)]);
          $("#range").append(new Option(label, key));
        }
        break;
      }
    }
  }
}

function svgNode(tag, attributes = {}, text = "") {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes))
    node.setAttribute(key, value);
  node.textContent = text;
  return node;
}

function drawChart() {
  const chart = $("#chart");
  chart.replaceChildren();
  $("#tooltip").textContent =
    "Hover over or focus a bar to see its time and price.";
  const valid = validIntervals();
  if (!valid.length) {
    chart.textContent =
      "No price intervals to display. Load a sample scenario or check your test data.";
    $("#chart-date").textContent = "";
    return;
  }
  const allStart = Math.min(...valid.map((r) => Date.parse(r.start)));
  const allEnd = Math.max(...valid.map((r) => Date.parse(r.end)));
  const [minTime, maxTime] = views.get($("#range").value) || [allStart, allEnd];
  const visible = valid.filter(
    (r) => Date.parse(r.end) > minTime && Date.parse(r.start) < maxTime,
  );
  $("#chart-date").textContent =
    `${date(minTime)}${date(minTime) !== date(maxTime - 1) ? " – " + date(maxTime - 1) : ""} · Times in ${timezone()}`;
  const prices = valid.map((r) => r.price);
  const low = Math.min(0, ...prices);
  const high = Math.max(0, ...prices);
  const span = high - low || 1;
  const x = (time) => 55 + ((time - minTime) / (maxTime - minTime)) * 650;
  const y = (price) => 302 - ((price - low + span * 0.08) / (span * 1.2)) * 250;
  const svg = svgNode("svg", {
    viewBox: "0 0 730 360",
    role: "group",
    "aria-label": `Electricity price in SEK per kWh, times in ${timezone()}`,
  });
  svg.append(svgNode("text", { x: 55, y: 20 }, "SEK/kWh"));
  if (result) {
    const start = Math.max(minTime, Date.parse(result.start));
    const end = Math.min(maxTime, Date.parse(result.end));
    if (end > start)
      svg.append(
        svgNode("rect", {
          x: x(start),
          y: 35,
          width: x(end) - x(start),
          height: 275,
          fill: "#eaf3e5",
          "data-highlight": "best-period",
        }),
      );
  }
  for (let i = 0; i <= 4; i++) {
    const price = low + (span * i) / 4;
    svg.append(
      svgNode("line", {
        x1: 55,
        x2: 705,
        y1: y(price),
        y2: y(price),
        stroke: "#e5ebe2",
        "stroke-dasharray": "3 5",
      }),
    );
    svg.append(
      svgNode(
        "text",
        { x: 44, y: y(price) + 4, "text-anchor": "end" },
        number.format(price),
      ),
    );
  }
  for (const r of visible) {
    const selected = Boolean(
      result &&
        Date.parse(r.start) >= Date.parse(result.start) &&
        Date.parse(r.end) <= Date.parse(result.end),
    );
    const description = `${stamp(r.start)} – ${stamp(r.end)} · ${number.format(r.price)} SEK/kWh${selected ? " · Best running period" : ""}`;
    const rect = svgNode("rect", {
      x: x(Math.max(minTime, Date.parse(r.start))),
      y: Math.min(y(r.price), y(0)) - (r.price === 0 ? 1 : 0),
      width:
        x(Math.min(maxTime, Date.parse(r.end))) -
        x(Math.max(minTime, Date.parse(r.start))),
      height: Math.max(2, Math.abs(y(r.price) - y(0))),
      fill: selected ? "#36845b" : "#a7bca9",
      stroke: "white",
      "stroke-width": 1,
      tabindex: 0,
      role: "img",
      "aria-label": description,
      "data-selected": selected,
      "data-start": r.start,
      "data-end": r.end,
    });
    rect.append(svgNode("title", {}, description));
    for (const event of ["mouseenter", "focus", "click"])
      rect.addEventListener(event, () => {
        $("#tooltip").textContent = description;
      });
    svg.append(rect);
  }
  for (let i = 0; i <= 4; i++) {
    const time = minTime + ((maxTime - minTime) * i) / 4;
    svg.append(
      svgNode(
        "text",
        { x: x(time), y: 331, "text-anchor": "middle" },
        clock(time),
      ),
    );
    if (date(minTime) !== date(maxTime))
      svg.append(
        svgNode(
          "text",
          { x: x(time), y: 347, "text-anchor": "middle" },
          format(time, { day: "numeric", month: "short" }),
        ),
      );
  }
  svg.append(
    svgNode(
      "text",
      { x: 705, y: 360, "text-anchor": "end" },
      `Time · ${timezone()}`,
    ),
  );
  chart.append(svg);
  if (valid.length !== sample.intervals.length)
    $("#tooltip").textContent =
      "Some invalid intervals cannot be plotted. Check the test data before calculating.";
}

function renderResult() {
  if (!result) return;
  $("#start-time").textContent = clock(result.start);
  $("#end-time").textContent = clock(result.end);
  $("#start-date").textContent = date(result.start);
  $("#end-date").textContent = date(result.end);
  $("#running-duration").textContent = duration(result.duration_minutes);
  $("#average-price").textContent = number.format(result.average_price);
  $("#status").textContent =
    `Lowest average price for your run · ${timezone()}`;
  $("#result").hidden = false;
}

function updateSummary() {
  $("#search-summary").textContent = sample
    ? `Allowed search period: ${stamp(sample.window_start)} – ${stamp(sample.window_end)}. All graph views use this same period.`
    : "";
}

function friendlyError(message) {
  if (message.includes("No continuous"))
    return "No uninterrupted period fits this duration exactly. Try another duration or sample; missing prices cannot be crossed and price intervals cannot be split.";
  if (message.startsWith("Duration"))
    return "Choose a positive running duration that fits within the available search period.";
  return (
    "We couldn’t find a recommendation. Check the sample data in Developer/Test data. " +
    message
  );
}

async function calculate() {
  invalidate();
  if (!sample || !$("#calculator").reportValidity()) return;
  const requestRevision = revision;
  $("#calculate").disabled = true;
  $(".recommendation").setAttribute("aria-busy", "true");
  $("#status").textContent = "Finding the best time for your appliance…";
  try {
    const response = await fetch("/api/calculate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...sample,
        duration_minutes: Number($("#duration").value),
      }),
    });
    const data = await response.json();
    if (revision !== requestRevision) return;
    if (!response.ok) {
      $("#status").textContent = "No suitable running period available";
      $("#error").textContent = friendlyError(
        data.error || "Please try again.",
      );
      $("#error").hidden = false;
      return;
    }
    result = data;
    renderResult();
    drawChart();
  } catch {
    if (revision !== requestRevision) return;
    $("#status").textContent = "Prices couldn’t be checked";
    $("#error").textContent =
      "The local planner is unavailable. Make sure the demo server is running, then try again.";
    $("#error").hidden = false;
  } finally {
    if (revision === requestRevision) {
      $("#calculate").disabled = false;
      $(".recommendation").setAttribute("aria-busy", "false");
    }
  }
}

function selectDuration() {
  for (const button of document.querySelectorAll("[data-minutes]"))
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.minutes === $("#duration").value),
    );
}
function loadScenario() {
  const selected = scenarios.find((s) => s.id === $("#scenario").value);
  sample = {
    intervals: selected.intervals,
    window_start: selected.window_start,
    window_end: selected.window_end,
  };
  $("#test-data").value = JSON.stringify(sample, null, 2);
  $("#editor-error").hidden = true;
  updateViews();
  updateSummary();
  calculate();
}
$("#calculator").addEventListener("submit", (event) => {
  event.preventDefault();
  calculate();
});
for (const button of document.querySelectorAll("[data-minutes]"))
  button.addEventListener("click", () => {
    $("#duration").value = button.dataset.minutes;
    selectDuration();
    calculate();
  });
$("#duration").addEventListener("input", () => {
  selectDuration();
  invalidate();
});
$("#duration").addEventListener("change", calculate);
$("#scenario").addEventListener("change", loadScenario);
$("#range").addEventListener("change", drawChart);
$("#timezone").addEventListener("change", () => {
  updateViews();
  updateSummary();
  renderResult();
  drawChart();
});
$("#apply-data").addEventListener("click", () => {
  invalidate();
  try {
    const data = JSON.parse($("#test-data").value);
    if (
      !data ||
      !Array.isArray(data.intervals) ||
      !data.intervals.every((r) => r && typeof r === "object") ||
      !Number.isFinite(Date.parse(data.window_start)) ||
      !Number.isFinite(Date.parse(data.window_end))
    )
      throw new Error(
        "Supply an intervals array and valid window_start/window_end timestamps.",
      );
    sample = {
      intervals: data.intervals,
      window_start: data.window_start,
      window_end: data.window_end,
    };
    $("#scenario").value = "";
    $("#editor-error").hidden = true;
    updateViews();
    updateSummary();
    calculate();
  } catch (error) {
    $("#editor-error").textContent =
      `Test data could not be applied. ${error.message}`;
    $("#editor-error").hidden = false;
    $("#status").textContent =
      "Test data could not be applied. The graph still shows the last loaded sample.";
  }
});
async function initialize() {
  const localZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (!["UTC", "Europe/Stockholm"].includes(localZone))
    $("#timezone").append(new Option(`${localZone} (local)`, localZone));
  try {
    const response = await fetch("/api/scenarios");
    if (!response.ok) throw new Error("Sample prices unavailable");
    scenarios = await response.json();
    if (!scenarios.length) throw new Error("No sample prices");
    for (const s of scenarios) $("#scenario").append(new Option(s.label, s.id));
    $("#scenario").disabled = false;
    loadScenario();
  } catch {
    $("#status").textContent =
      "Example prices couldn’t be loaded. Reload the page to try again.";
    $(".recommendation").setAttribute("aria-busy", "false");
    $("#calculate").disabled = true;
  }
}
initialize();
