/* Local-only SQLite worker. Retain the database after save loading so
 * underground tunnel details can be requested without reading the file again.
 */
let runtimePromise = null;
let readerPromise = null;
let tunnelsPromise = null;
let searchPromise = null;
let database = null;
const layoutCache = new Map();
const MAX_CACHED_WORLDS = 12;

async function getSavedLayout(worldId) {
  if (layoutCache.has(worldId)) return layoutCache.get(worldId);
  const { extractTerrainTunnels } = await openTunnels();
  const result = extractTerrainTunnels(database, worldId);
  if (layoutCache.size >= MAX_CACHED_WORLDS) {
    layoutCache.delete(layoutCache.keys().next().value);
  }
  layoutCache.set(worldId, result);
  return result;
}


function openRuntime() {
  if (!runtimePromise) {
    importScripts("./vendor/sql-wasm.js");
    if (typeof self.initSqlJs !== "function") {
      throw new Error("Bundled SQLite runtime could not be loaded");
    }
    runtimePromise = self.initSqlJs({
      locateFile: (filename) =>
        new URL("./vendor/" + filename, self.location.href).href,
    });
  }
  return runtimePromise;
}

function openReader() {
  readerPromise ??= import("./save-reader.mjs");
  return readerPromise;
}

function openTunnels() {
  tunnelsPromise ??= import("./tunnel-reader.mjs");
  return tunnelsPromise;
}

function openSearch() {
  searchPromise ??= import("./map-search.mjs");
  return searchPromise;
}

function checkedWorldIds(ids) {
  if (!Array.isArray(ids) || ids.length > 32
    || ids.some((id) => !Number.isSafeInteger(id) || id < 1 || id === 65535)) {
    throw new Error("Invalid underground world list (maximum 32 worlds per batch)");
  }
  return [...new Set(ids)];
}

self.addEventListener("message", async ({ data }) => {
  if (!data || !["read", "tunnels", "coverage", "search-index"].includes(data.type)) {
    self.postMessage({ type: "error", requestId: data?.requestId,
      message: "Invalid worker request" });
    return;
  }
  try {
    if (data.type === "read") {
      if (!(data.buffer instanceof ArrayBuffer)) {
        throw new Error("Invalid save file buffer");
      }
      if (database) { database.close(); database = null; }
      layoutCache.clear();
      const { assertSqliteHeader, extractSaveData } = await openReader();
      const bytes = new Uint8Array(data.buffer);
      assertSqliteHeader(bytes);
      const SQL = await openRuntime();
      const opened = new SQL.Database(bytes);
      let result;
      try {
        result = extractSaveData(opened);
      } catch (error) {
        opened.close();
        throw error;
      }
      database = opened;
      self.postMessage({ type: "result", requestId: data.requestId, result });
    } else if (data.type === "tunnels") {
      if (!database) throw new Error("Select a save before exploring tunnels");
      const result = await getSavedLayout(data.worldId);
      self.postMessage({ type: "tunnels", requestId: data.requestId, result });
    } else if (data.type === "coverage") {
      if (!database) throw new Error("Select a save before examining world coverage");
      const { summarizeSavedLayout } = await openTunnels();
      const summary = [];
      for (const worldId of checkedWorldIds(data.worldIds)) {
        summary.push(summarizeSavedLayout(await getSavedLayout(worldId)));
      }
      self.postMessage({ type: "coverage", requestId: data.requestId,
        result: summary });
    } else {
      if (!database) throw new Error("Select a save before searching saved assets");
      const { indexSavedObjects } = await openSearch();
      const entries = [];
      // Return only compact metadata, not raw ScriptData blobs or SQLite rows.
      for (const worldId of checkedWorldIds(data.worldIds)) {
        const layout = await getSavedLayout(worldId);
        for (const object of indexSavedObjects(layout)) {
          entries.push({ ...object, worldId });
        }
      }
      self.postMessage({ type: "search-index", requestId: data.requestId,
        result: entries });
    }
  } catch (error) {
    self.postMessage({ type: "error", requestId: data.requestId,
      message: error instanceof Error ? error.message : String(error) });
  }
});
