/* Classic worker: all save parsing and SQLite work happen off the UI thread.
 * No HTTP requests are made for save data; the WASM runtime uses local assets.
 */
let runtimePromise = null;
let readerPromise = null;

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

self.addEventListener("message", async ({ data }) => {
  if (!data || data.type !== "read" || !(data.buffer instanceof ArrayBuffer)) {
    self.postMessage({ type: "error", message: "Invalid worker request" });
    return;
  }

  try {
    const { assertSqliteHeader, extractSaveData } = await openReader();
    const bytes = new Uint8Array(data.buffer);
    assertSqliteHeader(bytes);
    const SQL = await openRuntime();
    const database = new SQL.Database(bytes);
    let result;
    try {
      result = extractSaveData(database);
    } finally {
      database.close();
    }
    self.postMessage({ type: "result", result });
  } catch (error) {
    self.postMessage({
      type: "error",
      message: error instanceof Error ? error.message : String(error),
    });
  }
});
