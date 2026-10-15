import { buildWorldGraph } from "./save-reader.mjs";
import { preferredUndergroundWorld } from "./tunnel-reader.mjs";
import { portalCellsForWorld, groupPortalCells, portalCellOverlapsPlacement } from "./portal-cells.mjs";
import { FULL_MAP_VIEW, MAX_MAP_ZOOM, zoomMapView,
  panMapView, mapZoomPercent, focusMapView } from "./map-camera.mjs";
import { indexSavedObjects, searchSavedObjects,
  searchSavedObjectsAcrossWorlds } from "./map-search.mjs";
import { availableElevationBands, elevationBand, placementOverlapsBand,
  visibleTunnelPaths } from "./elevation-slice.mjs";
import { analyzeTunnelPlacementContacts } from "./tunnel-contacts.mjs";

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
let activeGeometry = null;
let selectedCaveGroupId = null;
let selectedPocketIndex = null;
let selectedPocketGroupId = null;
let selectedPortalKey = null;
let selectedTunnelId = null;
let coverageEpoch = 0;
let manuallySelectedWorld = false;
let undergroundCoverage = new Map();
let mapView = { ...FULL_MAP_VIEW };
let mapDrag = null;
let mapProjection = null;
let globalSearchIndex = [];
let globalIndexEpoch = 0;
let globalIndexState = "idle";
let pendingSearchTarget = null;
let elevationBounds = null;
const requests = new Map();

async function enableOfflineAccess() {
  const status = $("offline-status");
  if (!("serviceWorker" in navigator) || !window.isSecureContext) {
    status.textContent = "Offline use requires HTTPS or localhost";
    status.dataset.state = "unavailable";
    return;
  }
  try {
    await navigator.serviceWorker.register(
      new URL("./service-worker.js", import.meta.url), { scope: "./" });
    await navigator.serviceWorker.ready;
    status.textContent = "App files cached · ready for offline use";
    status.dataset.state = "ready";
  } catch {
    // A failed optional cache must never prevent normal local save reading.
    status.textContent = "Offline cache unavailable · online use still works";
    status.dataset.state = "unavailable";
  }
}
void enableOfflineAccess();

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
    button.dataset.worldId = String(world.id);
    button.classList.toggle("active", world.id === selected);
    const title = element("div", "world-entry-title");
    title.append(element("span", "", world.label));
    if (world.depth !== null) title.append(element("span", "depth", "D" + world.depth));
    const subtitle = element("div", "world-entry-sub");
    subtitle.append(element("span", "", "#" + world.id));
    subtitle.append(element("span", "", formatKind(world.kind)));
    if (world.kind === "underground") {
      const info = undergroundCoverage.get(world.id);
      const labels = {
        tunnels: "Saved tunnel map",
        placements: "Saved placements only",
        "no-layout": "No saved layout data",
        unavailable: "Layout data unavailable",
        unsupported: "Layout exceeds limit",
      };
      subtitle.append(element("span", "coverage-label " + (info?.status || "pending"),
        info ? labels[info.status] || "Not mapped" : "Checking layout…"));
    }
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

function applyMapView() {
  $("tunnel-map").setAttribute("viewBox",
    [mapView.x, mapView.y, mapView.width, mapView.height].join(" "));
  $("map-zoom-level").textContent = mapZoomPercent(mapView) + "%";
  $("map-zoom-in").disabled = mapZoomPercent(mapView) >= MAX_MAP_ZOOM * 100;
  $("map-zoom-out").disabled = mapZoomPercent(mapView) <= 100;
}

function resetMapView() {
  mapView = { ...FULL_MAP_VIEW };
  mapDrag = null;
  $("tunnel-map").classList.remove("is-dragging");
  applyMapView();
}

function zoomMap(factor, clientX = null, clientY = null) {
  const rect = $("tunnel-map").getBoundingClientRect();
  const ax = clientX === null || !rect.width ? 0.5
    : (clientX - rect.left) / rect.width;
  const ay = clientY === null || !rect.height ? 0.5
    : (clientY - rect.top) / rect.height;
  mapView = zoomMapView(mapView, factor, ax, ay);
  applyMapView();
}

function resetElevationControls() {
  elevationBounds = null;
  $("height-mode").value = "all";
  $("height-mode").disabled = true;
  $("height-band").min = "0";
  $("height-band").max = "0";
  $("height-band").value = "0";
  $("height-band").disabled = true;
  $("height-band-label").textContent = "All saved heights";
}

function configureElevationControls(result) {
  elevationBounds = availableElevationBands(result.tunnels || [], result.footprints || []);
  $("height-mode").value = "all";
  $("height-mode").disabled = !elevationBounds;
  if (elevationBounds) {
    $("height-band").min = String(elevationBounds.min);
    $("height-band").max = String(elevationBounds.max);
    $("height-band").value = String(elevationBounds.min);
  }
  updateElevationControls();
}

function updateElevationControls() {
  const active = $("height-mode").value === "band" && Boolean(elevationBounds);
  $("height-band").disabled = !active;
  const band = active ? elevationBand(Number($("height-band").value)) : null;
  $("height-band-label").textContent = band
    ? "Saved Z " + band.low + " to " + band.high + " (16-unit slice)"
    : "All saved heights";
  if (activeGeometry) drawTunnelMap(activeGeometry);
}

function activeElevationBand() {
  return $("height-mode").value === "band" && elevationBounds
    ? elevationBand(Number($("height-band").value)) : null;
}

function focusSavedSearchResult(item) {
  if (!activeGeometry || !mapProjection) return false;
  // Validate against the active world, not stale results from a prior save.
  const present = indexSavedObjects(activeGeometry).some((candidate) =>
    candidate.kind === item.kind && candidate.id === item.id
    && candidate.index === item.index && candidate.x === item.x
    && candidate.y === item.y);
  if (!present) return false;
  // A result may be hidden by an unrelated height slice. Always reveal it.
  if (activeElevationBand()) {
    $("height-mode").value = "all";
    updateElevationControls();
  }
  selectedTunnelId = item.kind === "tunnel" ? item.id : null;
  selectedCaveGroupId = item.kind === "group" ? item.id : null;
  selectedPocketIndex = item.kind === "pocket" ? item.index
    : item.kind === "pocket-group" ? item.index : null;
  selectedPocketGroupId = item.kind === "pocket-group" ? item.id : null;
  selectedPortalKey = null;
  drawTunnelMap(activeGeometry);
  if (mapProjection) {
    const point = mapProjection(item.x, item.y);
    mapView = focusMapView(point.x, point.y, 4);
    applyMapView();
  }
  return true;
}

/** Interactive map navigation among saved allocation bounds, never entrances. */
function renderTunnelContactList(container, contacts) {
  const explorer = element("div", "tunnel-contact-explorer");
  explorer.append(element("div", "tunnel-contact-note",
    "Recorded tile-allocation bounds only. Selecting a contact inspects its "
    + "saved placement; no doorway or walkable route is established."));

  for (const [category, heading, targets] of [
    ["xyz", "XYZ bounding-box contacts", contacts.xyzTargets],
    ["xy-only", "XY-only overlaps at different heights", contacts.xyOnlyTargets],
  ]) {
    const section = element("details", "tunnel-contact-section");
    section.dataset.contactCategory = category;
    section.open = targets.length > 0 && targets.length <= 8;
    const summary = element("summary", "",
      heading + " (" + targets.length + ")");
    section.append(summary);
    const list = element("div", "tunnel-contact-items");
    if (!targets.length) list.append(element("div", "tunnel-contact-empty",
      "No recorded placement bounds in this category."));
    for (const target of targets) {
      if (!target.kind) {
        list.append(element("div", "tunnel-contact-unresolved",
          target.label + " · original placement not independently identified"));
        continue;
      }
      const button = element("button", "tunnel-contact-target", target.label);
      button.type = "button";
      button.dataset.contactKind = category;
      button.setAttribute("aria-label",
        "Inspect " + target.label + " from " + heading);
      button.addEventListener("click", () => {
        if (!activeGeometry) return;
        const item = indexSavedObjects(activeGeometry).find((candidate) =>
          candidate.kind === target.kind
          && candidate.id === target.id && candidate.index === target.index);
        if (!item) return;
        // Make the target visible even if its optional layer was hidden.
        if (item.kind === "group") $("show-caves").checked = true;
        else $("show-pockets").checked = true;
        focusSavedSearchResult(item);
      });
      list.append(button);
    }
    section.append(list);
    explorer.append(section);
  }
  container.append(explorer);
}

function updateObjectSearch() {
  const list = $("map-search-results");
  list.replaceChildren();
  const query = $("map-search-input").value.trim();
  const category = $("map-search-category").value;
  const status = $("map-search-status");
  const all = $("map-search-scope").value === "all";
  let indexed;
  if (all) {
    if (globalIndexState !== "ready") {
      status.textContent = globalIndexState === "error"
        ? "Could not index all underground worlds. Current-world search remains available."
        : "Indexing saved structures across underground worlds locally…";
      return;
    }
    indexed = globalSearchIndex;
  } else {
    if (!activeGeometry) {
      status.textContent = "Select an underground world to search its saved objects.";
      return;
    }
    indexed = indexSavedObjects(activeGeometry);
  }
  if (!query && category === "all") {
    status.textContent = "Search " + indexed.length + " saved placements and tunnel centerlines "
      + (all ? "across all underground worlds." : "in this world.")
      + " Choose a category to browse without typing.";
    return;
  }
  const { matches, total } = all
    ? searchSavedObjectsAcrossWorlds(indexed, query, 30, category)
    : searchSavedObjects(indexed, query, 30, category);
  status.textContent = total + " matching saved object" + (total === 1 ? "" : "s")
    + (total > matches.length ? " · showing first " + matches.length : "");
  for (const match of matches) {
    const button = element("button", "map-search-result");
    button.type = "button";
    const destination = all ? save?.worlds.find((w) => w.id === match.worldId) : null;
    button.append(element("span", "map-search-name", match.label));
    button.append(element("span", "map-search-detail",
      (destination ? destination.label + " · " : "") + match.details));
    button.addEventListener("click", () => {
      if (all && match.worldId !== selected) {
        pendingSearchTarget = match;
        selectWorld(match.worldId);
      } else if (activeGeometry) {
        focusSavedSearchResult(match);
      } else if (all) {
        pendingSearchTarget = match;
        selectWorld(match.worldId);
      }
    });
    list.append(button);
  }
}

async function indexAllUndergroundWorlds() {
  const epoch = ++globalIndexEpoch;
  const ids = save?.worlds.filter((w) => w.kind === "underground").map((w) => w.id) || [];
  globalSearchIndex = [];
  globalIndexState = "loading";
  updateObjectSearch();
  try {
    const entries = [];
    // Worker accepts small batches and reuses its existing decoded-world cache.
    for (let offset = 0; offset < ids.length; offset += 32) {
      const batch = await askWorker({
        type: "search-index", worldIds: ids.slice(offset, offset + 32),
      });
      if (epoch !== globalIndexEpoch) return;
      entries.push(...batch);
    }
    if (epoch !== globalIndexEpoch) return;
    globalSearchIndex = entries;
    globalIndexState = "ready";
    updateObjectSearch();
  } catch (error) {
    if (epoch !== globalIndexEpoch) return;
    globalSearchIndex = [];
    globalIndexState = "error";
    updateObjectSearch();
  }
}


function portalKey(cell) {
  return cell.cellX + ":" + cell.cellY;
}

function renderPortalGroupInfo(info, group, footprints) {
  info.replaceChildren();
  const n = group.endpoints.length;
  info.append(element("div", "portal-detail-heading",
    n + " saved portal endpoint" + (n === 1 ? "" : "s") +
    " in grid cell (" + group.cellX + ", " + group.cellY + ")" +
    (portalCellOverlapsPlacement(group, footprints)
      ? " · saved tile placement overlaps this cell"
      : " · no recorded tile placement at this cell")));
  info.append(element("div", "portal-detail-note",
    "The cell is a 64 × 64 region; exact doorway positions, heights and walkability remain unknown."));
  const entries = element("div", "portal-destinations");
  for (const endpoint of group.endpoints) {
    const row = element("div", "portal-destination-row");
    row.append(element("span", "portal-record-id",
      "Portal #" + endpoint.portalId + " · side " + endpoint.sides +
      (endpoint.linked ? "" : " · unresolved")));
    const destination = save.worlds.find((w) => w.id === endpoint.otherWorldId);
    if (destination) {
      const button = element("button", "portal-go", "Open " + destination.label);
      button.type = "button";
      button.addEventListener("click", () => selectWorld(destination.id));
      row.append(button);
    } else {
      row.append(element("span", "portal-unresolved",
        endpoint.otherWorldId === null
          ? "Destination not recorded" : "World #" + endpoint.otherWorldId + " not in save"));
    }
    entries.append(row);
  }
  info.append(entries);
}

function drawPortalCellLayer(root, result, groups, footprints, px, py, scale) {
  if (!$("show-portals").checked) return;
  for (const group of groups) {
    const count = group.endpoints.length;
    const selectedCell = selectedPortalKey === portalKey(group);
    const box = svg("rect", {
      x: px(group.x).toFixed(2), y: py(group.y + group.depth).toFixed(2),
      width: Math.max(0.5, group.width * scale).toFixed(2),
      height: Math.max(0.5, group.depth * scale).toFixed(2),
      class: "portal-cell" + (selectedCell ? " active" : ""),
      role: "button", tabindex: "0",
      "data-cell-x": group.cellX, "data-cell-y": group.cellY,
      "aria-label": "Inspect " + count + " saved portal endpoint"
        + (count === 1 ? "" : "s") + " in grid cell "
        + group.cellX + ", " + group.cellY,
    });
    box.append(svg("title", {},
      count + " saved portal endpoint" + (count === 1 ? "" : "s")
      + " · grid cell (" + group.cellX + ", " + group.cellY + ")"
      + " · records " + group.endpoints.map((p) => "#" + p.portalId).join(", ")
      + " · door positions in this cell are UNKNOWN"));
    const select = () => {
      selectedPortalKey = portalKey(group);
      selectedCaveGroupId = null;
      selectedPocketIndex = null;
      selectedPocketGroupId = null;
      selectedTunnelId = null;
      drawTunnelMap(result);
    };
    box.addEventListener("click", select);
    box.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        select();
      }
    });
    root.append(box);
    root.append(svg("text", {
      x: (px(group.x) + 4).toFixed(2),
      y: (py(group.y + group.depth) - 7).toFixed(2),
      class: "portal-cell-label",
    }, count > 1 ? "P×" + count : "P" + group.endpoints[0].portalId));
  }
}

function drawTunnelMap(result) {
  mapProjection = null;
  const root = $("tunnel-map");
  root.replaceChildren();
  applyMapView();
  root.append(svg("rect", {
    x: 0, y: 0, width: FULL_MAP_VIEW.width, height: FULL_MAP_VIEW.height,
    class: "map-pan-surface",
  }));
  const status = $("tunnel-status");
  const portalCells = portalCellsForWorld(save?.portals || [], selected);
  const portalGroups = groupPortalCells(portalCells);
  const layoutUnavailable = result.status !== "available";
  status.classList.toggle("warning", layoutUnavailable);
  const explanations = {
    "no-script-data": "This save has no ScriptData table; underground placements are unavailable.",
    "unavailable": "No compatible terrain record could be decoded for this world.",
    "no-tunnels": "The decoded record has no tunnel lines or cave placements.",
    "too-large": "Saved underground geometry exceeds the current display limit.",
  };
  if (layoutUnavailable && !portalCells.length) {
    $("cave-group-info").textContent = "No logical cave placements or portal cells available.";
    status.textContent = explanations[result.status] || "Saved underground geometry is unavailable.";
    return;
  }

  const tunnels = layoutUnavailable ? [] : (result.tunnels || []);
  const band = activeElevationBand();
  const footprints = layoutUnavailable ? [] : (result.footprints || []);
  const groups = result.caveGroups || [];
  const pocketGroups = result.pocketGroups || [];
  const visibleFootprint = (piece) => placementOverlapsBand(piece, band);
  const visibleLines = [];
  if ($("show-tunnels").checked) {
    for (const tunnel of tunnels) {
      for (const points of visibleTunnelPaths(tunnel.points, band)) {
        visibleLines.push({tunnel,points});
      }
    }
  }
  const pocketFragmentToGroup = new Map();
  for (const group of pocketGroups) {
    for (const index of group.fragments) pocketFragmentToGroup.set(index, group);
  }
  const groupInfo = $("cave-group-info");
  const selectedGroup = groups.find((g) => g.id === selectedCaveGroupId);
  const selectedPocket = footprints[selectedPocketIndex];
  const selectedPocketGroup = pocketGroups.find((g) => g.id === selectedPocketGroupId);
  const selectedPortalGroup = portalGroups.find((group) =>
    portalKey(group) === selectedPortalKey);
  const selectedTunnel = tunnels.find((t) => t.id === selectedTunnelId);
  const contacts = selectedTunnel
    ? analyzeTunnelPlacementContacts(selectedTunnel, footprints, groups, pocketGroups)
    : null;
  const touchingXYZ = new Set(contacts?.xyzIndices || []);
  const projectedOnly = new Set(contacts?.xyOnlyIndices || []);
  const groupAsset = selectedGroup?.asset;
  if (selectedPortalGroup) {
    renderPortalGroupInfo(groupInfo, selectedPortalGroup, footprints);
  } else if (selectedTunnel) {
    const zs = selectedTunnel.points.map((p) => p[2]);
    groupInfo.textContent = "Saved tunnel #" + selectedTunnel.id
      + " · recorded type " + selectedTunnel.type
      + " · " + selectedTunnel.points.length + " saved centerline points"
      + " · line length " + selectedTunnel.length.toFixed(1)
      + " saved-coordinate units"
      + " · recorded Z " + Math.min(...zs).toFixed(1)
      + " to " + Math.max(...zs).toFixed(1)
      + ". This saved centerline is NOT a verified open or walkable route."
      + " Saved placement bounding boxes touched in XYZ: "
      + contacts.xyzPlacements.length
      + (contacts.xyzPlacements.length
        ? " (" + contacts.xyzPlacements.slice(0,4).join(", ")
          + (contacts.xyzPlacements.length > 4 ? ", …" : "") + ")" : "")
      + " · XY projection only at a different height: "
      + contacts.xyOnlyPlacements.length
      + (contacts.xyOnlyPlacements.length
        ? " (" + contacts.xyOnlyPlacements.slice(0,4).join(", ")
          + (contacts.xyOnlyPlacements.length > 4 ? ", …" : "") + ")" : "")
      + ". Bounding-box contact does NOT verify an entrance, physical opening or clearance.";
    renderTunnelContactList(groupInfo, contacts);
  } else if (selectedGroup) {
    groupInfo.textContent = "Placement group #" + selectedGroup.id
      + " · " + (groupAsset
        ? groupAsset.name + " [catalog asset: " + groupAsset.family + "]"
        : "Unknown game tile (not in catalog)")
      + " · " + selectedGroup.fragmentCount + " saved cave cells"
      + (selectedGroup.sourceAware
        ? " · source-aware placement · source coverage "
          + (selectedGroup.sourceComplete ? "complete" : "INCOMPLETE")
          + " · overlapping source cells " + selectedGroup.sourceOverlapCells
        : " · adjacency-only candidate; exact identity unverified")
      + " · tile index " + selectedGroup.tileIndex
      + " · bounds " + selectedGroup.width + " × " + selectedGroup.depth
      + " × " + selectedGroup.height + " saved units"
      + " · rotation " + selectedGroup.rotation
      + (selectedGroup.expectedFragments !== null
        ? " · expected " + selectedGroup.expectedFragments + " fragments"
          + " · fragment count " + (selectedGroup.countMatches ? "matches" : "DIFFERS")
          + " · catalog size " + (selectedGroup.sizeMatches ? "matches" : "DIFFERS")
        : " · no known catalog dimensions")
      + ". Catalog names describe saved assets; room interior and walkability are unknown.";
  } else if (selectedPocketGroup) {
    groupInfo.textContent = "Logical pocket placement #" + selectedPocketGroup.id
      + " · " + selectedPocketGroup.asset.name
      + " [catalog asset: " + selectedPocketGroup.asset.family + "]"
      + " · " + selectedPocketGroup.fragmentCount + " saved fragments"
      + " · source coverage " + (selectedPocketGroup.sourceComplete ? "complete" : "INCOMPLETE")
      + " · catalog dimensions " + (selectedPocketGroup.sizeMatches ? "match" : "DIFFER")
      + " · overlapping source chunks " + selectedPocketGroup.sourceOverlapChunks
      + " · bounds " + selectedPocketGroup.width + " × "
      + selectedPocketGroup.depth + " × " + selectedPocketGroup.height
      + " saved units · rotation " + selectedPocketGroup.rotation
      + ". Source placement identity is supported by packed offsets, "
      + "but walkability and interior geometry are unverified.";
  } else if (selectedPocket?.kind === "pocket") {
    const asset = selectedPocket.asset;
    groupInfo.textContent = "Pocket placement · "
      + (asset ? asset.name + " [catalog asset: " + asset.family + "]"
        : "Unknown game tile (not in catalog)")
      + " · tile index " + selectedPocket.tileIndex
      + " · XY " + selectedPocket.x + ", " + selectedPocket.y
      + " · size " + selectedPocket.width + " × " + selectedPocket.depth
      + " × " + selectedPocket.height
      + (asset?.tags.length ? " · filename hints: " + asset.tags.join(", ") : "")
      + ". Asset naming does not prove entrances or accessible routes.";
  } else {
    const named = groups.filter((g) => g.asset).length;
    const namedPockets = footprints.filter((p) => p.kind === "pocket" && p.asset).length;
    groupInfo.textContent = named + "/" + groups.length
      + " named cave groups · " + pocketGroups.length + " reconstructed pocket placements"
      + " from " + namedPockets + " recognized fragments"
      + " · " + portalCells.length + " portal endpoints across "
      + portalGroups.length + " grid cells"
      + " · " + tunnels.length + " saved tunnel lines"
      + " · Select a placement, portal cell or tunnel line to inspect saved facts."
      + " No actual door positions or walkable passages are inferred.";
  }
  const fragmentToGroup = new Map();
  for (const g of groups) {
    for (const index of g.fragments) fragmentToGroup.set(index, g);
  }
  // Extents include both recorded tunnel points and placement boundaries,
  // even if their display layer is switched off, to preserve the map scale.
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  let minZ = Infinity, maxZ = -Infinity, pathPoints = 0;
  for (const tunnel of tunnels) {
    for (const [x, y, z] of tunnel.points) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
      minZ = Math.min(minZ, z); maxZ = Math.max(maxZ, z);
      pathPoints++;
    }
  }
  for (const item of footprints) {
    minX = Math.min(minX, item.x); maxX = Math.max(maxX, item.x + item.width);
    minY = Math.min(minY, item.y); maxY = Math.max(maxY, item.y + item.depth);
    minZ = Math.min(minZ, item.z); maxZ = Math.max(maxZ, item.z + item.height);
  }
  // Keep cell regions inside the viewport even when a world has no terrain record.
  for (const cell of portalCells) {
    minX = Math.min(minX, cell.x); maxX = Math.max(maxX, cell.x + cell.width);
    minY = Math.min(minY, cell.y); maxY = Math.max(maxY, cell.y + cell.depth);
  }
  if (![minX, maxX, minY, maxY].every(Number.isFinite)) {
    status.textContent = "No valid saved coordinates were found.";
    return;
  }

  const width = 880, height = 490, padX = 60, padY = 57;
  const scale = Math.min(width / Math.max(1, maxX - minX),
    height / Math.max(1, maxY - minY));
  const dx = (width - (maxX - minX) * scale) / 2;
  const dy = (height - (maxY - minY) * scale) / 2;
  const px = (x) => padX + dx + (x - minX) * scale;
  const py = (y) => padY + dy + (maxY - y) * scale;
  mapProjection = (x,y) => ({x:px(x),y:py(y)});
  const caves = footprints.filter((item) => item.kind === "cave");
  const pockets = footprints.filter((item) => item.kind === "pocket");
  status.textContent = layoutUnavailable
    ? (explanations[result.status] || "Terrain record unavailable.")
      + " " + portalCells.length + " saved portal endpoints across "
      + portalGroups.length + " grid cells can still be plotted."
    : tunnels.length + " tunnel lines · " + caves.length
      + " cave cells in " + groups.length + " placement groups ("
      + groups.filter((g) => g.sourceAware).length + " source-aware) · "
      + pockets.length + " pocket placements · "
      + portalCells.length + " portal endpoints in " + portalGroups.length + " cells · "
      + pathPoints + " tunnel points · Z " + minZ.toFixed(1)
      + " to " + maxZ.toFixed(1)
      + " · source record #" + result.rowId
      + (result.failed ? " · " + result.failed + " unsupported records skipped" : "")
      + (band ? " · Z " + band.low + " to " + band.high
        + ": " + caves.filter(visibleFootprint).length + " cave cells, "
        + pockets.filter(visibleFootprint).length + " pocket fragments, "
        + visibleLines.length + " visible tunnel line sections"
        + " · portal heights unknown (always shown)" : "");

  root.append(svg("text", { x: 45, y: 27, class: "tunnel-extents" },
    "SAVED PLAN VIEW · +X RIGHT / +Y UP"));
  root.append(svg("text", { x: 45, y: 603, class: "tunnel-extents" },
    "X " + minX.toFixed(1) + "… " + maxX.toFixed(1)
    + "  ·  Y " + minY.toFixed(1) + "… " + maxY.toFixed(1)));

  for (const [index, item] of footprints.entries()) {
    const group = fragmentToGroup.get(index);
    const pocketGroup = pocketFragmentToGroup.get(index);
    const enabled = $(item.kind === "cave" ? "show-caves" : "show-pockets").checked;
    if (!enabled || !visibleFootprint(item)) continue;
    const box = svg("rect", {
      x: px(item.x).toFixed(2),
      y: py(item.y + item.depth).toFixed(2),
      width: Math.max(0.5, item.width * scale).toFixed(2),
      height: Math.max(0.5, item.depth * scale).toFixed(2),
      class: "saved-footprint " + item.kind
        + (touchingXYZ.has(index) ? " line-contact-xyz"
          : projectedOnly.has(index) ? " line-projection-only" : "")
        + (group && group.id === selectedCaveGroupId ? " group-selected" : "")
        + (item.kind === "pocket" && (selectedPocketIndex === index
          || (pocketGroup && pocketGroup.id === selectedPocketGroupId))
          ? " placement-selected" : ""),
      tabindex: "0", role: "button",
      "aria-label": item.kind === "pocket"
        ? "Inspect pocket asset " + (item.asset?.name || "unknown")
        : "Inspect cave placement group " + (group?.id || "unknown"),
    });
    box.append(svg("title", {},
      (item.kind === "cave" ? "Cave cell" : "Pocket placement")
      + " · tile index " + item.tileIndex
      + " · XY " + item.x + ", " + item.y
      + " · " + item.width + " × " + item.depth
      + " · Z " + item.z + "… " + (item.z + item.height)
      + " · rotation " + item.rotation
      + (item.asset ? " · asset " + item.asset.name
        + " · catalog tags " + (item.asset.tags.join(", ") || "none")
        : " · catalog asset unknown")
      + (group ? " · logical group #" + group.id : "")
      + (pocketGroup ? " · logical pocket #" + pocketGroup.id : "")));
    const choose = () => {
      selectedCaveGroupId = group?.id || null;
      selectedPocketIndex = item.kind === "pocket" ? index : null;
      selectedPocketGroupId = item.kind === "pocket" ? (pocketGroup?.id ?? null) : null;
      selectedPortalKey = null;
      selectedTunnelId = null;
      drawTunnelMap(result);
    };
    box.addEventListener("click", choose);
    box.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        choose();
      }
    });
    root.append(box);
  }

  // Dashed outlines are group bounding boxes, not claimed room walls.
  if ($("show-groups").checked) {
    for (const group of groups) {
      if (group.fragmentCount < 2
        || !group.fragments.some((i) => visibleFootprint(footprints[i]))) continue;
      const outline = svg("rect", {
        x: px(group.x).toFixed(2),
        y: py(group.y + group.depth).toFixed(2),
        width: Math.max(0.5, group.width * scale).toFixed(2),
        height: Math.max(0.5, group.depth * scale).toFixed(2),
        class: "cave-group" + (group.id === selectedCaveGroupId ? " active" : ""),
        role: "button", tabindex: "0",
        "aria-label": "Inspect logical placement group " + group.id,
      });
      outline.append(svg("title", {},
        "Logical placement group #" + group.id + " · "
        + (group.asset ? "catalog asset " + group.asset.name : "unknown game tile")
        + " · " + group.fragmentCount + " adjacent cells, tile index "
        + group.tileIndex + " · rectangular extents only; room interior unverified"));
      const choose = () => {
        selectedCaveGroupId = group.id;
        selectedPocketIndex = null;
        selectedPocketGroupId = null;
        selectedPortalKey = null;
        selectedTunnelId = null;
        drawTunnelMap(result);
      };
      outline.addEventListener("click", choose);
      outline.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          choose();
        }
      });
      root.append(outline);
      root.append(svg("text", {
        x: (px(group.x) + 4).toFixed(1),
        y: (py(group.y + group.depth) - 7).toFixed(1),
        class: "cave-group-label",
      }, group.asset?.family === "elevator" ? "ELEVATOR · G" + group.id
        : "G" + group.id));
    }
  }

  if ($("show-groups").checked && $("show-pockets").checked) {
    for (const group of pocketGroups) {
      if (group.fragmentCount < 2
        || !group.fragments.some((i) => visibleFootprint(footprints[i]))) continue;
      const outline = svg("rect", {
        x: px(group.x).toFixed(2),
        y: py(group.y + group.depth).toFixed(2),
        width: Math.max(0.5, group.width * scale).toFixed(2),
        height: Math.max(0.5, group.depth * scale).toFixed(2),
        class: "pocket-group" + (group.id === selectedPocketGroupId ? " active" : ""),
        role: "button", tabindex: "0",
        "aria-label": "Inspect logical pocket placement " + group.id,
      });
      outline.append(svg("title", {}, "Logical pocket placement #" + group.id
        + " · " + group.asset.name + " · " + group.fragmentCount
        + " fragments · stored rectangular extent only"));
      const choose = () => {
        selectedCaveGroupId = null;
        selectedPocketIndex = group.fragments[0];
        selectedPocketGroupId = group.id;
        selectedPortalKey = null;
        selectedTunnelId = null;
        drawTunnelMap(result);
      };
      outline.addEventListener("click", choose);
      outline.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          choose();
        }
      });
      root.append(outline);
      root.append(svg("text", {
        x: (px(group.x) + 4).toFixed(1),
        y: (py(group.y + group.depth) - 7).toFixed(1),
        class: "pocket-group-label",
      }, "PG" + group.id));
    }
  }

  for (const {tunnel, points} of visibleLines) {
    const coordinates = points.map(([x, y]) => px(x).toFixed(1)
      + "," + py(y).toFixed(1)).join(" ");
    const path = svg("polyline", {
      points: coordinates, class: "tunnel-line"
        + (selectedTunnelId === tunnel.id ? " active" : ""),
      "data-tunnel-id": tunnel.id, role: "button", tabindex: "0",
      "aria-label": "Inspect saved tunnel " + tunnel.id + ", " + tunnel.type,
    });
    path.append(svg("title", {},
      "Tunnel #" + tunnel.id + " · " + tunnel.type
      + (band ? " · section intersecting saved Z " + band.low + " to " + band.high
        : " · " + tunnel.length.toFixed(1) + " saved-coordinate units")
      + " · centerline only, not verified walkability"));
    const choose = () => {
      selectedTunnelId = tunnel.id;
      selectedCaveGroupId = null;
      selectedPocketIndex = null;
      selectedPocketGroupId = null;
      selectedPortalKey = null;
      drawTunnelMap(result);
    };
    path.addEventListener("click", choose);
    path.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        choose();
      }
    });
    root.append(path);
  }
  drawPortalCellLayer(root, result, portalGroups, footprints, px, py, scale);
}

async function loadSelectedTunnels() {
  const epoch = ++tunnelSelectionEpoch;
  resetMapView();
  activeGeometry = null;
  mapProjection = null;
  resetElevationControls();
  updateObjectSearch();
  selectedCaveGroupId = null;
  selectedPocketIndex = null;
  selectedPocketGroupId = null;
  selectedPortalKey = null;
  selectedTunnelId = null;
  $("cave-group-info").textContent = "Select a saved placement, portal or tunnel to inspect it.";
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
    activeGeometry = result;
    configureElevationControls(result);
    if (pendingSearchTarget?.worldId === world.id) {
      const requested = pendingSearchTarget;
      pendingSearchTarget = null;
      focusSavedSearchResult(requested);
    }
    updateObjectSearch();
  } catch (error) {
    if (epoch !== tunnelSelectionEpoch) return;
    $("tunnel-status").classList.add("warning");
    updateObjectSearch();
    $("tunnel-status").textContent = "Cannot inspect this world: "
      + (error instanceof Error ? error.message : String(error));
  }
}

function selectWorld(id, automatic = false) {
  if (pendingSearchTarget && pendingSearchTarget.worldId !== id) {
    pendingSearchTarget = null;
  }
  if (!automatic) manuallySelectedWorld = true;
  if (selected === id && activeGeometry) return;
  selected = id;
  displayWorldList();
  displayGraph();
  displayDetails();
  void loadSelectedTunnels();
}

async function inspectUndergroundCoverage() {
  const epoch = ++coverageEpoch;
  const underground = sortedWorlds().filter((w) => w.kind === "underground");
  const sampled = underground.slice(0, 32);
  const summary = $("world-coverage-summary");
  if (!underground.length) {
    summary.textContent = "No underground world definitions found in this save.";
    return;
  }
  summary.textContent = "Checking saved underground layout data…";
  try {
    const scanned = await askWorker({
      type: "coverage", worldIds: sampled.map((w) => w.id),
    });
    if (epoch !== coverageEpoch) return;
    undergroundCoverage = new Map(scanned.map((c) => [c.worldId, c]));
    const mapped = scanned.filter((c) =>
      c.status === "tunnels" || c.status === "placements").length;
    const withTunnels = scanned.filter((c) => c.status === "tunnels").length;
    summary.textContent = mapped + " of " + sampled.length
      + " checked underground worlds have saved layout data"
      + " (" + withTunnels + " with tunnel lines)"
      + (underground.length > sampled.length ? "; remaining worlds not scanned" : "")
      + ". Unmapped does not mean the cave is physically empty.";
    displayWorldList();
    if (!manuallySelectedWorld) {
      const preferred = preferredUndergroundWorld(save.worlds, scanned);
      if (preferred !== null && selected !== preferred) selectWorld(preferred, true);
    }
  } catch (error) {
    if (epoch !== coverageEpoch) return;
    summary.textContent = "Could not inspect underground layout coverage: "
      + (error instanceof Error ? error.message : String(error));
  }
}

function showSave(data, fileName) {
  ++globalIndexEpoch;
  globalSearchIndex = [];
  globalIndexState = "idle";
  pendingSearchTarget = null;
  manuallySelectedWorld = false;
  undergroundCoverage = new Map();
  save = data;
  graph = buildWorldGraph(data.worlds, data.portals);
  selected = preferredUndergroundWorld(data.worlds, []);
  $("save-name").textContent = fileName;
  $("stat-worlds").textContent = data.worlds.length;
  $("stat-underground").textContent =
    data.worlds.filter((w) => w.kind === "underground").length;
  $("stat-portals").textContent = data.portals.length;
  $("stat-links").textContent = graph.edges.length;
  $("world-filter").value = "all";
  $("map-search-input").value = "";
  $("map-search-scope").value = "current";
  $("map-search-category").value = "all";
  $("explorer").classList.remove("is-hidden");
  displayWorldList();
  displayGraph();
  displayDetails();
  void loadSelectedTunnels();
  void inspectUndergroundCoverage();
  void indexAllUndergroundWorlds();
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
  resetMapView();
  ++coverageEpoch;
  ++globalIndexEpoch;
  globalSearchIndex = [];
  globalIndexState = "idle";
  pendingSearchTarget = null;
  resetElevationControls();
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

$("map-search-input").addEventListener("input", updateObjectSearch);
$("map-search-scope").addEventListener("change", updateObjectSearch);
$("height-mode").addEventListener("change", updateElevationControls);
$("height-band").addEventListener("input", updateElevationControls);
$("map-search-category").addEventListener("change", updateObjectSearch);
$("map-zoom-in").addEventListener("click", () => zoomMap(1.5));
$("map-zoom-out").addEventListener("click", () => zoomMap(1 / 1.5));
$("map-zoom-reset").addEventListener("click", resetMapView);

const mapSvg = $("tunnel-map");
mapSvg.addEventListener("wheel", (event) => {
  // Prevent page scrolling only while the pointer is over the map itself.
  event.preventDefault();
  zoomMap(event.deltaY < 0 ? 1.25 : 1 / 1.25, event.clientX, event.clientY);
}, { passive: false });

mapSvg.addEventListener("pointerdown", (event) => {
  // Do not intercept clicks on portal/cave/pocket selection targets.
  if (event.button !== 0 || (event.target !== mapSvg
    && !event.target.classList?.contains("map-pan-surface"))) return;
  const rect = mapSvg.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  mapDrag = {
    pointerId: event.pointerId,
    originX: event.clientX, originY: event.clientY,
    originView: { ...mapView }, width: rect.width, height: rect.height,
  };
  mapSvg.setPointerCapture(event.pointerId);
  mapSvg.classList.add("is-dragging");
});
mapSvg.addEventListener("pointermove", (event) => {
  if (!mapDrag || event.pointerId !== mapDrag.pointerId) return;
  const dx = -(event.clientX - mapDrag.originX)
    * mapDrag.originView.width / mapDrag.width;
  const dy = -(event.clientY - mapDrag.originY)
    * mapDrag.originView.height / mapDrag.height;
  mapView = panMapView(mapDrag.originView, dx, dy);
  applyMapView();
});
function finishMapDrag(event) {
  if (!mapDrag || event.pointerId !== mapDrag.pointerId) return;
  mapDrag = null;
  mapSvg.classList.remove("is-dragging");
  if (mapSvg.hasPointerCapture(event.pointerId)) {
    mapSvg.releasePointerCapture(event.pointerId);
  }
}
mapSvg.addEventListener("pointerup", finishMapDrag);
mapSvg.addEventListener("pointercancel", finishMapDrag);
resetMapView();
resetElevationControls();

$("save-input").addEventListener("change", (event) =>
  loadSave(event.target.files?.[0]));
$("world-filter").addEventListener("change", displayWorldList);
for (const checkboxId of ["show-caves", "show-pockets", "show-tunnels", "show-groups", "show-portals"]) {
  $(checkboxId).addEventListener("change", () => {
    if (activeGeometry) drawTunnelMap(activeGeometry);
  });
}
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
