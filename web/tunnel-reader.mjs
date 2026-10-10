/**
 * Saved ScriptData terrain tunnel reader. A cross-checkable browser port of
 * sm_atlas.terrain_data_probe + formats.lua_values + underground_tunnels.
 *
 * Lines are saved tunnel centerlines, NOT verified walkable cave geometry.
 */
import { decodeLz4Block } from "./save-reader.mjs";

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
  const points = tunnels.reduce((total, tunnel) => total + tunnel.points.length, 0);
  if (points > 50000) {
    return { worldId, status: "too-large", tunnels: [], scanned, failed, points };
  }
  return { worldId, status: tunnels.length ? "available" : "no-tunnels",
    tunnels, scanned, failed, rowId: best.rowId, points };
}
