/**
 * Saved ScriptData terrain tunnel reader. A cross-checkable browser port of
 * sm_atlas.terrain_data_probe + formats.lua_values + underground_tunnels.
 *
 * Lines are saved tunnel centerlines, NOT verified walkable cave geometry.
 */
import { decodeLz4Block } from "./save-reader.mjs";
import { identifyTile } from "./tile-catalog.mjs";

const TERRAIN_KEYS = new Set([
  "bounds", "caves", "pockets", "rotation", "spawners",
  "tileList", "tunnels", "uid", "xOffset", "yOffset",
]);
const MAX_LUA_BYTES = 32 * 1024 * 1024;
const MAX_TABLE_ITEMS = 1_000_000;
const MAX_STRING_BYTES = 32 * 1024 * 1024;

class Bits {
  constructor(bytes) {
    this.bytes = bytes;
    this.position = 0;
  }
  require(count) {
    if (count < 0 || this.position + count > this.bytes.length * 8) {
      throw new Error("Truncated LUA record");
    }
  }
  bits(count) {
    this.require(count);
    if (count > 32) throw new Error("LUA integer width exceeds 32 bits");
    let value = 0;
    for (let bit = 0; bit < count; bit++) {
      const offset = this.position++;
      value = (value * 2) + ((this.bytes[offset >>> 3] >> (7 - (offset & 7))) & 1);
    }
    return value >>> 0;
  }
  signed(count) {
    const number = this.bits(count);
    if (count === 32) return number | 0;
    const sign = 2 ** (count - 1);
    return number >= sign ? number - 2 ** count : number;
  }
  byte() { return this.bits(8); }
  uint32() { return this.bits(32); }
  float32() {
    const bits = this.uint32();
    const view = new DataView(new ArrayBuffer(4));
    view.setUint32(0, bits, false);
    return view.getFloat32(0, false);
  }
  float64() {
    const view = new DataView(new ArrayBuffer(8));
    view.setUint32(0, this.uint32(), false);
    view.setUint32(4, this.uint32(), false);
    return view.getFloat64(0, false);
  }
  bytesOf(length, align = false) {
    if (!Number.isSafeInteger(length) || length < 0) {
      throw new Error("Invalid LUA byte length");
    }
    if (align && this.position % 8) this.position += 8 - (this.position % 8);
    this.require(length * 8);
    if (this.position % 8 === 0) {
      const index = this.position / 8;
      this.position += length * 8;
      return this.bytes.subarray(index, index + length);
    }
    return Uint8Array.from({ length }, () => this.byte());
  }
}

const looseText = new TextDecoder("utf-8");
function decodeValue(reader, depth = 0) {
  if (depth > 256) throw new Error("Maximum LUA nesting depth exceeded");
  const tag = reader.byte();
  if (tag === 0 || tag === 1) return null;
  if (tag === 2) return reader.bits(1) === 1;
  if (tag === 3) return reader.float32();
  if (tag === 4 || tag === 9) {
    const size = reader.uint32();
    if (size > MAX_STRING_BYTES) throw new Error("LUA string exceeds safety limit");
    const str = looseText.decode(reader.bytesOf(size, true));
    if (tag === 4) return str;
    try { return JSON.parse(str); } catch { return str; }
  }
  if (tag === 5) {
    const count = reader.uint32();
    if (count > MAX_TABLE_ITEMS) throw new Error("LUA table exceeds safety limit");
    const array = reader.bits(1) === 1;
    const table = new Map();
    if (array) {
      const first = reader.signed(32);
      for (let i = 0; i < count; i++) {
        table.set(first + i, decodeValue(reader, depth + 1));
      }
    } else {
      for (let i = 0; i < count; i++) {
        const key = decodeValue(reader, depth + 1);
        const value = decodeValue(reader, depth + 1);
        table.set(key, value);
      }
    }
    return table;
  }
  if (tag === 6) return reader.signed(32);
  if (tag === 7) return reader.signed(16);
  if (tag === 8) return reader.signed(8);
  if (tag === 11) return reader.float64();
  if (tag === 0x64) {
    const kind = reader.uint32();
    if (kind === 10001) return { type: "uuid", bytes: reader.bytesOf(16) };
    if (kind === 10003) {
      return { type: "vec3", x: reader.float32(), y: reader.float32(), z: reader.float32() };
    }
    if (kind === 10004) {
      return { type: "quat", x: reader.float32(), y: reader.float32(),
        z: reader.float32(), w: reader.float32() };
    }
    if (kind === 10005) {
      return { type: "color", r: reader.float32(), g: reader.float32(),
        b: reader.float32(), a: reader.float32() };
    }
    if ([10021,10023,10024,10025,10027,10028,10030,10036,10037,10039].includes(kind)) {
      return { type: "handle", kind, value: reader.uint32() };
    }
    throw new Error("Unknown LUA userdata kind " + kind);
  }
  throw new Error("Unsupported LUA tag 0x" + tag.toString(16));
}

export function decodeLuaValue(bytes) {
  if (!(bytes instanceof Uint8Array) || bytes.length < 7
      || bytes[0] !== 0x4c || bytes[1] !== 0x55 || bytes[2] !== 0x41) {
    throw new Error("Missing LUA record header");
  }
  const reader = new Bits(bytes);
  reader.bytesOf(3);
  if (reader.uint32() !== 1) throw new Error("Unsupported LUA version");
  return decodeValue(reader);
}

function u16(data, index) {
  if (index + 2 > data.length) throw new Error("Truncated ScriptData envelope");
  return data[index] * 256 + data[index + 1];
}
function u32(data, index) {
  if (index + 4 > data.length) throw new Error("Truncated ScriptData envelope");
  return data[index] * 0x1000000
    + data[index + 1] * 0x10000 + data[index + 2] * 256 + data[index + 3];
}

export function decodeScriptDataRecord(blob, expectedWorldId) {
  if (!(blob instanceof Uint8Array) || blob.length < 25) {
    throw new Error("ScriptData record is too short");
  }
  const keyLength = u16(blob, 16);
  const trailer = 18 + keyLength;
  if (trailer + 7 > blob.length) throw new Error("Truncated ScriptData envelope");
  const worldId = u16(blob, trailer);
  if (worldId !== expectedWorldId) throw new Error("ScriptData world ID mismatch");
  const compressedSize = u32(blob, trailer + 3);
  if (compressedSize !== blob.length - trailer - 7) {
    throw new Error("Invalid ScriptData compressed payload length");
  }
  const data = decodeLz4Block(blob.subarray(trailer + 7), MAX_LUA_BYTES);
  return { value: decodeLuaValue(data), rawSize: data.length };
}

export function extractSavedTunnels(value) {
  if (!(value instanceof Map)) return [];
  const rawTunnels = value.get("tunnels");
  if (!(rawTunnels instanceof Map)) return [];
  const output = [];
  for (const [id, rawTunnel] of rawTunnels) {
    if (!Number.isInteger(id) || !(rawTunnel instanceof Map)) continue;
    const rawPositions = rawTunnel.get("positions");
    if (!(rawPositions instanceof Map)) continue;
    const ordered = [...rawPositions.entries()]
      .filter(([idx, vec]) => Number.isInteger(idx) && vec?.type === "vec3"
        && [vec.x,vec.y,vec.z].every(Number.isFinite))
      .sort((a, b) => a[0] - b[0]);
    if (ordered.length < 2) continue;
    const points = ordered.map(([, vec]) => [vec.x, vec.y, vec.z]);
    let length = 0;
    for (let i = 1; i < points.length; i++) {
      length += Math.hypot(...points[i].map((v, axis) => v - points[i - 1][axis]));
    }
    const name = rawTunnel.get("tunnelType");
    output.push({ id, type: typeof name === "string" ? name : "Unknown", length, points });
  }
  output.sort((a, b) => a.id - b.id);
  return output;
}

/**
 * Decode the saved placement rectangles from caves/pockets grids.
 * These are tile allocation footprints, NOT empty space or collision bounds.
 * Mirrors Python underground_features._decode_cave/_decode_pocket.
 */
export function extractSavedFootprints(value) {
  const output = [];
  if (!(value instanceof Map)) return output;
  const lookup = new Map();
  const tileList = value.get("tileList");
  if (tileList instanceof Map) {
    for (const [index, item] of tileList) {
      if (!Number.isInteger(index) || item?.type !== "uuid" || !(item.bytes instanceof Uint8Array)
          || item.bytes.length !== 16) continue;
      // Python LuaUuid stores these on disk with reversed byte ordering.
      const hex = [...item.bytes].reverse().map((byte) =>
        byte.toString(16).padStart(2, "0")).join("");
      lookup.set(index, [hex.slice(0,8), hex.slice(8,12), hex.slice(12,16),
        hex.slice(16,20), hex.slice(20)].join("-"));
    }
  }
  for (const kind of ["cave", "pocket"]) {
    const grid = value.get(kind === "cave" ? "caves" : "pockets");
    if (!(grid instanceof Map)) continue;
    for (const [cellY, row] of grid) {
      if (!Number.isInteger(cellY) || !(row instanceof Map)) continue;
      for (const [cellX, entries] of row) {
        if (!Number.isInteger(cellX) || !(entries instanceof Map)) continue;
        for (const raw of entries.values()) {
          if (!Number.isInteger(raw) || typeof raw === "boolean") continue;
          const n = raw >>> 0;
          const tileIndex = n & 0xff;
          const tileUuid = lookup.get(tileIndex) || null;
          const asset = identifyTile(tileUuid);
          const rotation = kind === "cave" ? (n >>> 20) & 3 : (n >>> 28) & 3;
          let x = cellX * 64, y = cellY * 64, z, width, depth, height;
          if (kind === "cave") {
            z = ((n >>> 8) & 15) * 16;
            height = (((n >>> 12) & 15) + 1) * 16;
            width = depth = 64;
          } else {
            const placement = (n >>> 8) & 255;
            x += (placement & 3) * 16;
            y += ((placement >>> 2) & 3) * 16;
            z = ((placement >>> 4) & 15) * 16;
            const size = (n >>> 16) & 255;
            const w = ((size & 3) + 1) * 16;
            const d = (((size >>> 2) & 3) + 1) * 16;
            [width, depth] = rotation & 1 ? [d, w] : [w, d];
            height = (((size >>> 4) & 15) + 1) * 16;
          }
          if (![x, y, z, width, depth, height].every(Number.isFinite)) continue;
          output.push({
            kind, cellX, cellY, tileIndex, tileUuid, asset,
            rotation, x, y, z, width, depth, height,
          });
        }
      }
    }
  }
  return output;
}

/**
 * Reconstruct logical cave *placement groups* from face-connected cells.
 *
 * Mirrors Python reconstruct_logical_structures: adjacent cave fragments
 * share a physical cell face at the same saved Z, rotation and tile UUID.
 * When the tile UUID is absent, only the same saved tile index may group;
 * its semantic identity remains unknown. Groups DO NOT imply open rooms.
 */
export function reconstructCaveGroups(footprints) {
  const caveIndices = footprints.map((piece, i) =>
    piece.kind === "cave" ? i : -1).filter((i) => i >= 0);
  const buckets = new Map();
  const identityOf = (p) => p.tileUuid
    ? "uuid:" + p.tileUuid : "unresolved-index:" + p.tileIndex;
  const keyOf = (p, x = p.cellX, y = p.cellY) =>
    [identityOf(p), p.rotation, p.z, x, y].join("|");
  for (const index of caveIndices) {
    const p = footprints[index];
    const key = keyOf(p);
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(index);
  }
  const parent = new Map(caveIndices.map((index) => [index, index]));
  function find(i) {
    const p = parent.get(i);
    if (p !== i) parent.set(i, find(p));
    return parent.get(i);
  }
  function union(a, b) {
    const x = find(a), y = find(b);
    if (x !== y) parent.set(Math.max(x,y), Math.min(x,y));
  }
  for (const index of caveIndices) {
    const p = footprints[index];
    for (const [dx, dy] of [[-1,0], [1,0], [0,-1], [0,1]]) {
      for (const other of buckets.get(keyOf(p, p.cellX+dx, p.cellY+dy)) || []) {
        union(index, other);
      }
    }
  }
  const components = new Map();
  for (const index of caveIndices) {
    const root = find(index);
    if (!components.has(root)) components.set(root, []);
    components.get(root).push(index);
  }
  const groups = [...components.values()].map((indices) => {
    const parts = indices.map((i) => footprints[i]);
    const first = parts[0];
    const minX = Math.min(...parts.map((p) => p.x));
    const maxX = Math.max(...parts.map((p) => p.x+p.width));
    const minY = Math.min(...parts.map((p) => p.y));
    const maxY = Math.max(...parts.map((p) => p.y+p.depth));
    const minZ = Math.min(...parts.map((p) => p.z));
    const maxZ = Math.max(...parts.map((p) => p.z+p.height));
    const asset = identifyTile(first.tileUuid);
    // The catalog's filename encodes full tile dimensions in 16-m chunks.
    // Count and bounding-box agreement is a consistency check, NOT evidence
    // that all interior volume is empty or traversable.
    let sizeMatches = null, countMatches = null, expectedFragments = null;
    if (asset?.dimensions) {
      const [tileW, tileD, tileH] = asset.dimensions;
      expectedFragments = Math.ceil(tileW / 4) * Math.ceil(tileD / 4);
      countMatches = indices.length === expectedFragments;
      const [worldW, worldD] = first.rotation & 1 ? [tileD,tileW] : [tileW,tileD];
      sizeMatches = maxX-minX === worldW*16
        && maxY-minY === worldD*16 && maxZ-minZ === tileH*16;
    }
    return {
      tileIndex: first.tileIndex, tileUuid: first.tileUuid, asset,
      identityVerified: Boolean(first.tileUuid),
      sizeMatches, countMatches, expectedFragments,
      rotation: first.rotation, fragments: indices,
      fragmentCount: indices.length,
      x: minX, y: minY, z: minZ,
      width: maxX-minX, depth: maxY-minY, height: maxZ-minZ,
    };
  });
  groups.sort((a, b) =>
    a.z-b.z || a.y-b.y || a.x-b.x
    || (a.tileUuid || "").localeCompare(b.tileUuid || "")
    || a.tileIndex-b.tileIndex);
  return groups.map((g, index) => ({ id: index+1, ...g }));
}

/** Lightweight metadata for local save coverage; not a walkability verdict. */
export function summarizeSavedLayout(result) {
  const tunnels = result.tunnels?.length ?? 0;
  const footprints = result.footprints ?? [];
  const caveCells = footprints.filter((p) => p.kind === "cave").length;
  const pocketCells = footprints.filter((p) => p.kind === "pocket").length;
  let status = "no-layout";
  if (result.status === "too-large") status = "unsupported";
  else if (result.status === "unavailable") status = "unavailable";
  else if (result.status === "no-script-data") status = "unavailable";
  else if (tunnels > 0) status = "tunnels";
  else if (caveCells + pocketCells > 0) status = "placements";
  return {
    worldId: result.worldId, status, tunnels, caveCells, pocketCells,
    caveGroups: result.caveGroups?.length ?? 0,
  };
}

/** Cave-first default, favoring levels with actual saved lines over empty records. */
export function preferredUndergroundWorld(worlds, coverage) {
  const underground = worlds.filter((w) => w.kind === "underground")
    .sort((a, b) => (a.depth ?? Infinity) - (b.depth ?? Infinity) || a.id - b.id);
  const byId = new Map(coverage.map((c) => [c.worldId, c]));
  for (const status of ["tunnels", "placements"]) {
    const matching = underground.find((w) => byId.get(w.id)?.status === status);
    if (matching) return matching.id;
  }
  return underground[0]?.id ?? worlds[0]?.id ?? null;
}

export function extractTerrainTunnels(database, worldId, limit = 5000) {
  if (!Number.isSafeInteger(worldId) || worldId < 0) {
    throw new Error("Invalid selected world ID");
  }
  const tables = database.exec(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='ScriptData'",
  );
  if (!tables.length || !tables[0].values.length) {
    return { worldId, status: "no-script-data", tunnels: [], scanned: 0, failed: 0 };
  }
  const stmt = database.prepare(
    "SELECT rowid AS row_id, data FROM ScriptData WHERE worldId = ? AND data IS NOT NULL "
    + "ORDER BY length(data) DESC, rowid LIMIT ?",
  );
  let scanned = 0, failed = 0, best = null;
  try {
    stmt.bind([worldId, limit]);
    while (stmt.step()) {
      scanned++;
      const row = stmt.getAsObject();
      if (!(row.data instanceof Uint8Array)) { failed++; continue; }
      try {
        const decoded = decodeScriptDataRecord(row.data, worldId);
        if (!(decoded.value instanceof Map)) continue;
        const score = [...decoded.value.keys()].filter(
          (key) => typeof key === "string" && TERRAIN_KEYS.has(key),
        ).length;
        if (!score) continue;
        // Python's candidate ordering: signal key score then decompressed length.
        if (!best || score > best.score
          || (score === best.score && decoded.rawSize > best.rawSize)) {
          best = { score, rawSize: decoded.rawSize, rowId: row.row_id,
            value: decoded.value };
        }
      } catch {
        failed++;
      }
    }
  } finally {
    stmt.free();
  }
  if (!best) return { worldId, status: "unavailable", tunnels: [], scanned, failed };
  const tunnels = extractSavedTunnels(best.value);
  const footprints = extractSavedFootprints(best.value);
  const points = tunnels.reduce((total, tunnel) => total + tunnel.points.length, 0);
  if (points > 50000 || footprints.length > 20000) {
    return { worldId, status: "too-large", tunnels: [], footprints: [],
      scanned, failed, points, footprintsCount: footprints.length };
  }
  const caveGroups = reconstructCaveGroups(footprints);
  return { worldId, status: tunnels.length || footprints.length ? "available" : "no-tunnels",
    tunnels, footprints, caveGroups, scanned, failed, rowId: best.rowId, points };
}
