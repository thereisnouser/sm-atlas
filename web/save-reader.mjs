// Pure parsing layer shared by the browser UI and Node tests.
// Mirrors the independently researched Python world/portal record layouts.

export const WORLD_MARKER_UID = Uint8Array.from(
  "5297769df4514e5e9a388b0f95e2edad".match(/../g),
  (hex) => parseInt(hex, 16),
);
export const SQLITE_HEADER = "SQLite format 3\u0000";
const decoder = new TextDecoder("utf-8", { fatal: true });

function requireSize(data, offset, length) {
  if (offset < 0 || length < 0 || offset + length > data.length) {
    throw new Error("Truncated binary save record");
  }
}

function uint16(data, offset) {
  requireSize(data, offset, 2);
  return (data[offset] << 8) | data[offset + 1];
}

function uint32(data, offset) {
  requireSize(data, offset, 4);
  return (data[offset] * 0x1000000
    + (data[offset + 1] << 16)
    + (data[offset + 2] << 8)
    + data[offset + 3]) >>> 0;
}

export function decodeLz4Block(input, maxOutput = 1024 * 1024) {
  if (!(input instanceof Uint8Array)) throw new Error("Expected an LZ4 byte array");
  let cursor = 0;
  let size = 0;
  let output = new Uint8Array(Math.min(maxOutput, Math.max(64, input.length * 4)));
  function grow(end) {
    if (end > maxOutput) throw new Error("LZ4 output exceeds the safety limit");
    if (end > output.length) {
      let capacity = output.length;
      while (capacity < end) capacity = Math.min(maxOutput, Math.max(capacity * 2, end));
      const next = new Uint8Array(capacity);
      next.set(output.subarray(0, size));
      output = next;
    }
  }
  function readExtraLength(initial) {
    let length = initial;
    if (initial === 15) {
      let next;
      do {
        if (cursor >= input.length) throw new Error("Truncated LZ4 length");
        next = input[cursor++];
        length += next;
        if (length > maxOutput) throw new Error("LZ4 length exceeds limit");
      } while (next === 255);
    }
    return length;
  }
  while (cursor < input.length) {
    const token = input[cursor++];
    const literalLength = readExtraLength(token >> 4);
    requireSize(input, cursor, literalLength);
    grow(size + literalLength);
    output.set(input.subarray(cursor, cursor + literalLength), size);
    size += literalLength;
    cursor += literalLength;
    if (cursor === input.length) break;
    requireSize(input, cursor, 2);
    const offset = input[cursor] | (input[cursor + 1] << 8);
    cursor += 2;
    if (!offset || offset > size) throw new Error("Invalid LZ4 match offset");
    const length = readExtraLength(token & 15) + 4;
    grow(size + length);
    for (let i = 0; i < length; i++) output[size + i] = output[size + i - offset];
    size += length;
  }
  return output.slice(0, size);
}

function readText(data, start) {
  const length = uint16(data, start);
  const offset = start + 2;
  requireSize(data, offset, length);
  return [decoder.decode(data.subarray(offset, offset + length)), offset + length];
}

export function decodeWorldRecord(data, expectedWorldId) {
  if (!(data instanceof Uint8Array) || data.length < 29) {
    throw new Error("Invalid GenericData envelope");
  }
  const worldId = uint16(data, 22);
  if (worldId !== expectedWorldId) throw new Error("GenericData world ID mismatch");
  const compressedSize = data[28];
  let compressed = data.subarray(29);
  if (compressedSize > 0 && compressedSize <= compressed.length) {
    compressed = compressed.subarray(0, compressedSize);
  }
  const payload = decodeLz4Block(compressed);
  requireSize(payload, 0, 4);
  const seed = uint32(payload, 0);
  const [filename, cursor1] = readText(payload, 4);
  const [classname, cursor2] = readText(payload, cursor1);
  const [terrainRaw] = readText(payload, cursor2);
  let terrain = terrainRaw;
  try { terrain = JSON.parse(terrainRaw); } catch { /* preserve original */ }
  const kind = classname === "Overworld" ? "overworld"
    : classname === "DungeonWorld" ? "dungeon"
    : classname === "WarehouseWorld" ? "warehouse"
    : classname.startsWith("UndergroundWorld") ? "underground"
    : "other";
  const depth = terrain && typeof terrain === "object"
    && Number.isFinite(terrain.depth) ? Math.trunc(terrain.depth) : null;
  let label = classname || "World " + worldId;
  if (kind === "warehouse" && terrain && typeof terrain === "object"
      && Number.isFinite(terrain.warehouseIndex) && Number.isFinite(terrain.level)) {
    label = (terrain.isQuestWarehouse === true ? "Quest Warehouse " : "Warehouse ")
      + Math.trunc(terrain.warehouseIndex) + " L" + Math.trunc(terrain.level)
      + (Number.isFinite(terrain.maxLevels) ? "/" + Math.trunc(terrain.maxLevels) : "");
  } else if (terrain && typeof terrain === "object") {
    const path = terrain.path || terrain.worldFilePath;
    if (typeof path === "string" && path) {
      const filenameBase = path.replace(/\\/g, "/").split("/").at(-1).replace(/\.[^.]+$/, "");
      if (filenameBase) label = kind === "underground" && depth !== null
        ? "D" + depth + " " + filenameBase : filenameBase;
    }
  }
  return { id: worldId, kind, label, depth, seed, classname, filename };
}

function rows(db, sql, bind) {
  const statement = db.prepare(sql);
  try {
    if (bind !== undefined) statement.bind(bind);
    const values = [];
    while (statement.step()) values.push(statement.getAsObject());
    return values;
  } finally {
    statement.free();
  }
}

function integer(value) {
  const number = Number(value);
  return Number.isSafeInteger(number) ? number : null;
}

export function extractSaveData(db) {
  const tables = new Set(rows(db,
    "SELECT name FROM sqlite_master WHERE type='table'").map((row) => row.name));
  if (!tables.has("GenericData")) {
    throw new Error("Not a supported Scrap Mechanic save: GenericData table is missing");
  }
  const warnings = [];
  const worlds = [];
  const worldRows = rows(db, "SELECT worldId, data FROM GenericData WHERE uid=? AND flags=3 ORDER BY worldId",
    [WORLD_MARKER_UID]);
  for (const row of worldRows) {
    const id = integer(row.worldId);
    if (id === null) { warnings.push("Skipped a world with an invalid ID"); continue; }
    try { worlds.push(decodeWorldRecord(row.data, id)); }
    catch { warnings.push("Could not decode world " + id); }
  }
  const portals = [];
  if (tables.has("Portal")) {
    // Portal table columns are saved facts. Do not assume player traversal.
    for (const row of rows(db,
      "SELECT id, worldIdA, xA, yA, worldIdB, xB, yB FROM Portal ORDER BY id")) {
      const values = [row.id, row.worldIdA, row.xA, row.yA, row.worldIdB, row.xB, row.yB].map(integer);
      if (values.some((v) => v === null)) { warnings.push("Skipped invalid portal row"); continue; }
      const [id, worldA, xA, yA, worldB, xB, yB] = values;
      portals.push({ id, worldA, xA, yA, worldB, xB, yB,
        resolved: worldA !== 65535 && worldB !== 65535 });
    }
  }
  return { worlds, portals, tables: [...tables].sort(), warnings };
}

export function buildWorldGraph(worlds, portals) {
  const byId = new Map(worlds.map((world) => [world.id, world]));
  const edges = portals.filter((portal) => portal.resolved
    && byId.has(portal.worldA) && byId.has(portal.worldB));
  const connected = new Set();
  for (const edge of edges) { connected.add(edge.worldA); connected.add(edge.worldB); }
  return { edges, connected, missingWorldReferences: portals.filter((p) => p.resolved
    && (!byId.has(p.worldA) || !byId.has(p.worldB))).length };
}

export function assertSqliteHeader(bytes) {
  if (!(bytes instanceof Uint8Array) || bytes.length < 100) {
    throw new Error("The selected file is too small to be a SQLite save");
  }
  const header = String.fromCharCode(...bytes.subarray(0, 16));
  if (header !== SQLITE_HEADER) {
    throw new Error("This is not a SQLite save.db file");
  }
}
