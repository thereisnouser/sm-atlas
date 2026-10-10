import { buildWorldGraph } from "./save-reader.mjs";

const $ = (id) => document.getElementById(id);
const ns = "http://www.w3.org/2000/svg";
const bucketOrder = ["overworld", "underground", "warehouse", "dungeon", "other"];
let save = null;
let graph = null;
let selected = null;
let busy = false;
let saveWorker = null;
let requestNumber = 0;
let tunnelSelectionEpoch = 0;
const requests = new Map();

function svg(tag, attributes = {}, content) {
  const element = document.createElementNS(ns, tag);
  for (const [name, value] of Object.entries(attributes)) {
    element.setAttribute(name, String(value));
  }
  if (content !== undefined) element.textContent = String(content);
  return element;
}

function element(tag, className, text) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text !== undefined) result.textContent = String(text);
  return result;
}

function setMessage(text, isError = false) {
  $("message").textContent = text;
  $("message").classList.toggle("error", isError);
}

function formatKind(kind) {
  return kind[0].toUpperCase() + kind.slice(1);
}

function sortedWorlds() {
  return [...save.worlds].sort((a, b) =>
    bucketOrder.indexOf(a.kind) - bucketOrder.indexOf(b.kind)
    || (a.depth ?? 999) - (b.depth ?? 999)
    || a.id - b.id);
}

function displayWorldList() {
  const list = $("world-list");
  list.replaceChildren();
  const kind = $("world-filter").value;
  const shown = sortedWorlds().filter((w) => kind === "all" || w.kind === kind);
  if (!shown.length) {
    list.append(element("div", "empty", "No worlds match this filter."));
  }
  for (const world of shown) {
    const button = element("button", "world-entry");
    button.type = "button";
    button.classList.toggle("active", world.id === selected);
    const title = element("div", "world-entry-title");
    title.append(element("span", "", world.label));
    if (world.depth !== null) title.append(element("span", "depth", "D" + world.depth));
    const subtitle = element("div", "world-entry-sub");
    subtitle.append(element("span", "", "#" + world.id));
    subtitle.append(element("span", "", formatKind(world.kind)));
    button.append(title, subtitle);
    button.addEventListener("click", () => selectWorld(world.id));
    list.append(button);
  }
}

function displayGraph() {
  const root = $("world-graph");
  root.replaceChildren();
  const worlds = sortedWorlds();
  if (!worlds.length) {
    root.setAttribute("viewBox", "0 0 1080 440");
    root.append(svg("text", { x: 540, y: 200, fill: "#8a9ca9", "text-anchor": "middle" },
      "No world records found in this save"));
    return;
  }

  const cols = 4, xDistance = 263, yDistance = 132;
  const height = Math.max(420, Math.ceil(worlds.length / cols) * yDistance + 70);
  root.setAttribute("viewBox", "0 0 1080 " + height);
  const coordinates = new Map();
  worlds.forEach((world, index) => {
    coordinates.set(world.id, {
      x: 135 + (index % cols) * xDistance,
      y: 92 + Math.floor(index / cols) * yDistance,
    });
  });

  const lines = svg("g", { "aria-hidden": "true" });
  for (const portal of graph.edges) {
    const a = coordinates.get(portal.worldA), b = coordinates.get(portal.worldB);
    if (!a || !b) continue;
    const active = selected === portal.worldA || selected === portal.worldB;
    const path = portal.worldA === portal.worldB
      ? "M " + (a.x + 86) + " " + a.y + " C " + (a.x + 115) + " "
        + (a.y - 65) + " " + (a.x - 115) + " " + (a.y - 65)
        + " " + (a.x - 86) + " " + a.y
      : "M " + a.x + " " + a.y + " L " + b.x + " " + b.y;
    const line = svg("path", {
      d: path, class: "graph-link" + (active ? " active" : ""),
    });
    line.append(svg("title", {}, "Saved Portal #" + portal.id + ": world "
      + portal.worldA + " to world " + portal.worldB));
    lines.append(line);
  }
  root.append(lines);

  for (const world of worlds) {
    const { x, y } = coordinates.get(world.id);
    const group = svg("g", {
      class: "graph-node " + world.kind + (selected === world.id ? " active" : ""),
      role: "button", tabindex: "0", "aria-label": "Select " + world.label,
    });
    group.append(svg("rect", { x: x - 95, y: y - 30, width: 190, height: 64 }));
    const truncatedLabel = world.label.length > 23
      ? world.label.slice(0, 21) + "…" : world.label;
    group.append(svg("text", { x, y: y - 4, "text-anchor": "middle",
      "font-weight": "700" }, truncatedLabel));
    group.append(svg("text", { x, y: y + 17, class: "graph-id",
      "text-anchor": "middle" }, "#" + world.id + "  ·  " + formatKind(world.kind)));
    group.append(svg("title", {}, world.label + " — world " + world.id));
    group.addEventListener("click", () => selectWorld(world.id));
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectWorld(world.id);
      }
    });
    root.append(group);
  }
}

function displayDetails() {
  const container = $("world-details");
  container.replaceChildren();
  const world = save.worlds.find((w) => w.id === selected);
  if (!world) {
    container.append(element("div", "empty", "Choose a world."));
    return;
  }
  container.append(element("div", "detail-title", world.label));
  const tags = element("div", "detail-tags");
  const values = [
    "WORLD ID " + world.id,
    formatKind(world.kind).toUpperCase(),
    world.depth === null ? null : "DEPTH " + world.depth,
    "SEED " + world.seed,
  ].filter(Boolean);
  for (const value of values) tags.append(element("span", "detail-tag", value));
  container.append(tags);

  const connections = save.portals.filter(
    (p) => p.worldA === world.id || p.worldB === world.id,
  );
  const section = element("div", "portal-list");
  section.append(element("div", "eyebrow", connections.length
    + " SAVED PORTAL RECORD" + (connections.length === 1 ? "" : "S")));
  if (!connections.length) {
    section.append(element("div", "empty", "No portal record is connected to this world. This does not prove it is unreachable."));
  }
  for (const p of connections) {
    const other = p.worldA === world.id ? p.worldB : p.worldA;
    const thisCell = p.worldA === world.id
      ? [p.xA, p.yA] : [p.xB, p.yB];
    const otherCell = p.worldA === world.id
      ? [p.xB, p.yB] : [p.xA, p.yA];
    const target = save.worlds.find((w) => w.id === other);
    const item = element("div", "portal-item");
    item.append(element("span", "", "Portal #" + p.id + " → "
      + (target ? target.label + " (#" + other + ")" : "World #" + other)));
    item.append(element("small", "",
      "Cells (" + thisCell.join(", ") + ") → (" + otherCell.join(", ") + ")"
      + (p.resolved ? "" : " · unresolved")));
    section.append(item);
  }
  container.append(section);
}

function drawTunnelMap(result) {
  const root = $("tunnel-map");
  root.replaceChildren();
  root.setAttribute("viewBox", "0 0 1000 620");
  const status = $("tunnel-status");
  status.classList.toggle("warning", result.status !== "available");
  if (result.status !== "available") {
    const explanations = {
      "no-script-data": "This save contains no ScriptData table; tunnel lines are unavailable.",
      "unavailable": "No compatible underground terrain record was decoded for this world.",
      "no-tunnels": "The decoded terrain record contains no saved tunnel centerlines.",
      "too-large": "This world's saved centerline data exceeds the current display limit.",
    };
    status.textContent = explanations[result.status] || "Tunnel lines are unavailable for this world.";
    return;
  }

  const tunnels = result.tunnels;
  const all = tunnels.flatMap((tunnel) => tunnel.points);
  const xs = all.map((point) => point[0]), ys = all.map((point) => point[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const minZ = Math.min(...all.map((point) => point[2]));
  const maxZ = Math.max(...all.map((point) => point[2]));
  const width = 880, height = 490, padX = 60, padY = 57;
  const scale = Math.min(width / Math.max(1, maxX - minX),
    height / Math.max(1, maxY - minY));
  const dx = (width - (maxX - minX) * scale) / 2;
  const dy = (height - (maxY - minY) * scale) / 2;
  const px = (x) => padX + dx + (x - minX) * scale;
  const py = (y) => padY + dy + (maxY - y) * scale;
  status.textContent = tunnels.length + " saved tunnels · " + all.length
    + " path points · Z " + minZ.toFixed(1) + " to " + maxZ.toFixed(1)
    + " · decoded record #" + result.rowId
    + (result.failed ? " · " + result.failed + " unsupported records skipped" : "");

  root.append(svg("text", { x: 45, y: 27, class: "tunnel-extents" },
    "TOP-DOWN VIEW · +X RIGHT / +Y UP"));
  root.append(svg("text", { x: 45, y: 603, class: "tunnel-extents" },
    "X " + minX.toFixed(1) + "… " + maxX.toFixed(1)
    + "  ·  Y " + minY.toFixed(1) + "… " + maxY.toFixed(1)));
  for (const tunnel of tunnels) {
    const points = tunnel.points.map(([x,y]) => px(x).toFixed(1)
      + "," + py(y).toFixed(1)).join(" ");
    const path = svg("polyline", { points, class: "tunnel-line",
      tabindex: "0", "aria-label": "Tunnel " + tunnel.id + ", " + tunnel.type });
    path.append(svg("title", {},
      "Tunnel #" + tunnel.id + " · " + tunnel.type + " · "
      + tunnel.length.toFixed(1) + " saved-coordinate units"));
    root.append(path);
  }
}

async function loadSelectedTunnels() {
  const epoch = ++tunnelSelectionEpoch;
  const world = save?.worlds.find((item) => item.id === selected);
  const root = $("tunnel-map");
  root.replaceChildren();
  $("tunnel-status").classList.remove("warning");
  if (!world || world.kind !== "underground") {
    $("tunnel-status").textContent = "Select an underground world to inspect its saved tunnel lines.";
    return;
  }
  $("tunnel-status").textContent = "Reading saved underground tunnel coordinates for " + world.label + "…";
  try {
    const result = await askWorker({ type: "tunnels", worldId: world.id });
    if (epoch !== tunnelSelectionEpoch || selected !== world.id) return;
    drawTunnelMap(result);
  } catch (error) {
    if (epoch !== tunnelSelectionEpoch) return;
    $("tunnel-status").classList.add("warning");
    $("tunnel-status").textContent = "Cannot inspect this world: "
      + (error instanceof Error ? error.message : String(error));
  }
}

function selectWorld(id) {
  selected = id;
  displayWorldList();
  displayGraph();
  displayDetails();
  void loadSelectedTunnels();
}

function showSave(data, fileName) {
  save = data;
  graph = buildWorldGraph(data.worlds, data.portals);
  selected = sortedWorlds()[0]?.id ?? null;
  $("save-name").textContent = fileName;
  $("stat-worlds").textContent = data.worlds.length;
  $("stat-underground").textContent =
    data.worlds.filter((w) => w.kind === "underground").length;
  $("stat-portals").textContent = data.portals.length;
  $("stat-links").textContent = graph.edges.length;
  $("world-filter").value = "all";
  $("explorer").classList.remove("is-hidden");
  displayWorldList();
  displayGraph();
  displayDetails();
  void loadSelectedTunnels();
  const warnings = [...data.warnings];
  if (graph.missingWorldReferences) {
    warnings.push(graph.missingWorldReferences
      + " portal links refer to unavailable world definitions.");
  }
  $("warnings").textContent = warnings.join(" · ");
}

function disposeWorker(reason = "Previous save closed") {
  if (saveWorker) {
    saveWorker.terminate();
    saveWorker = null;
  }
  for (const pending of requests.values()) pending.reject(new Error(reason));
  requests.clear();
}

function askWorker(payload, transfer = []) {
  if (!saveWorker) {
    return Promise.reject(new Error("Local save reader is not available"));
  }
  return new Promise((resolve, reject) => {
    const requestId = ++requestNumber;
    requests.set(requestId, { resolve, reject });
    try {
      saveWorker.postMessage({ ...payload, requestId }, transfer);
    } catch (error) {
      requests.delete(requestId);
      reject(error);
    }
  });
}

function inspectLocalSave(buffer) {
  disposeWorker();
  saveWorker = new Worker(new URL("./save-worker.js", import.meta.url));
  saveWorker.onmessage = ({ data }) => {
    const pending = requests.get(data?.requestId);
    if (!pending) return;
    requests.delete(data.requestId);
    if (data.type === "error") pending.reject(new Error(data.message));
    else pending.resolve(data.result);
  };
  saveWorker.onerror = (event) => {
    event.preventDefault();
    disposeWorker("Local save reader failed to load or execute");
  };
  saveWorker.onmessageerror = () => {
    disposeWorker("Local save reader returned invalid data");
  };
  return askWorker({ type: "read", buffer }, [buffer]);
}

async function loadSave(file) {
  if (!file || busy) return;
  busy = true;
  // Close old saved data when the user selects another save.
  disposeWorker();
  ++tunnelSelectionEpoch;
  save = null;
  graph = null;
  selected = null;
  $("explorer").classList.add("is-hidden");
  setMessage("Reading " + file.name + " privately in a background worker…");
  try {
    const data = await inspectLocalSave(await file.arrayBuffer());
    showSave(data, file.name);
    setMessage("Loaded " + file.name + " · " + data.worlds.length
      + " world definitions · file processed locally, not uploaded.");
  } catch (error) {
    disposeWorker("Failed save was discarded");
    setMessage(error instanceof Error ? error.message : String(error), true);
  } finally {
    busy = false;
    $("save-input").value = "";
  }
}

$("save-input").addEventListener("change", (event) =>
  loadSave(event.target.files?.[0]));
$("world-filter").addEventListener("change", displayWorldList);
const dropZone = $("drop-zone");
for (const type of ["dragenter", "dragover"]) {
  dropZone.addEventListener(type, (event) => {
    event.preventDefault();
    dropZone.classList.add("is-over");
  });
}
for (const type of ["dragleave", "drop"]) {
  dropZone.addEventListener(type, (event) => {
    event.preventDefault();
    dropZone.classList.remove("is-over");
  });
}
dropZone.addEventListener("drop", (event) => {
  const file = event.dataTransfer?.files?.[0];
  if (file) void loadSave(file);
});
