import test from "node:test";
import assert from "node:assert/strict";
import {
  WORLD_MARKER_UID, assertSqliteHeader, decodeLz4Block,
  decodeWorldRecord, extractSaveData, buildWorldGraph,
} from "../save-reader.mjs";

const encoder = new TextEncoder();

function stringField(text) {
  const bytes = encoder.encode(text);
  if (bytes.length > 65535) throw Error("test string too large");
  return Uint8Array.from([bytes.length >> 8, bytes.length & 255, ...bytes]);
}
function intBytes(number, size) {
  const result = new Uint8Array(size);
  for (let i = size - 1; i >= 0; i--) {
    result[i] = number & 255;
    number >>>= 8;
  }
  return result;
}
function join(...chunks) {
  const output = new Uint8Array(chunks.reduce((n, item) => n + item.length, 0));
  let offset = 0;
  for (const chunk of chunks) { output.set(chunk, offset); offset += chunk.length; }
  return output;
}
function literalLz4(data) {
  const result = [Math.min(data.length, 15) << 4];
  if (data.length >= 15) {
    let remaining = data.length - 15;
    while (remaining >= 255) { result.push(255); remaining -= 255; }
    result.push(remaining);
  }
  return join(Uint8Array.from(result), data);
}
function worldEnvelope(worldId, classname, options = {}) {
  const terrain = options.terrain ?? "{}";
  const payload = join(
    intBytes(options.seed ?? 123456, 4),
    stringField(options.filename ?? "world.lua"),
    stringField(classname),
    stringField(terrain),
  );
  const compressed = literalLz4(payload);
  const header = new Uint8Array(29);
  header.set(WORLD_MARKER_UID, 0);
  header.set(intBytes(worldId, 2), 22);
  header[28] = compressed.length <= 255 ? compressed.length : 0;
  return join(header, compressed);
}
function mockDb(tables, worldRows, portalRows) {
  let activeBind = null;
  return {
    prepare(sql) {
      let index = 0;
      const result = sql.includes("sqlite_master")
        ? tables.map((name) => ({ name }))
        : sql.includes("FROM GenericData") ? worldRows
        : sql.includes("FROM Portal") ? portalRows : [];
      return {
        bind(values) { activeBind = values; },
        step() { return index < result.length; },
        getAsObject() { return result[index++]; },
        free() { },
      };
    },
    bound() { return activeBind; },
  };
}

test("LZ4 decoder handles literal and overlapping match data", () => {
  const source = encoder.encode("A long and honest Scrap Mechanic test save");
  assert.deepEqual(decodeLz4Block(literalLz4(source)), source);
  // token: one literal 'a', followed by an offset=1 match of 5 bytes
  assert.equal(new TextDecoder().decode(decodeLz4Block(
    Uint8Array.from([0x10, 97, 1, 0]),
  )), "aaaaa");
});

test("LZ4 decoder rejects malformed and oversized records", () => {
  assert.throws(() => decodeLz4Block(Uint8Array.from([0, 0, 0])), /offset/);
  assert.throws(() => decodeLz4Block(Uint8Array.from([0xf0])), /length/);
  assert.throws(() => decodeLz4Block(literalLz4(new Uint8Array(16)), 8), /limit/);
});

test("decode world envelope exactly as existing Python research", () => {
  const record = worldEnvelope(23, "UndergroundWorld", {
    terrain: '{"depth":6,"path":"$SURVIVAL_DATA/Scripts/worlds/Drill2.lua"}',
    seed: 7309,
  });
  const world = decodeWorldRecord(record, 23);
  assert.equal(world.id, 23);
  assert.equal(world.kind, "underground");
  assert.equal(world.depth, 6);
  assert.equal(world.label, "D6 Drill2");
  assert.equal(world.seed, 7309);
  assert.throws(() => decodeWorldRecord(record, 12), /world ID mismatch/);
  assert.throws(() => decodeWorldRecord(record.subarray(0, 28), 23), /envelope/);
});

test("classification never confuses unresolved depth with guessed mine level", () => {
  assert.equal(decodeWorldRecord(worldEnvelope(1, "Overworld"), 1).kind, "overworld");
  assert.equal(decodeWorldRecord(worldEnvelope(5, "WarehouseWorld", {
    terrain: '{"warehouseIndex":2,"level":1,"maxLevels":4}',
  }), 5).label, "Warehouse 2 L1/4");
  const other = decodeWorldRecord(worldEnvelope(7, "UndergroundWorldExtra"), 7);
  assert.equal(other.kind, "underground");
  assert.equal(other.depth, null);
});

test("local schema extraction uses byte-bound world marker and saved portal columns", () => {
  const fake = mockDb(
    ["GenericData", "Portal"],
    [{ worldId: 23, data: worldEnvelope(23, "UndergroundWorld", {
      terrain: '{"depth":6}',
    }) }, { worldId: 3, data: Uint8Array.from([1, 2]) }],
    [{ id: 67, worldIdA: 12, xA: -2, yA: 2,
      worldIdB: 23, xB: 0, yB: 0 },
    { id: 68, worldIdA: 23, xA: 1, yA: 1,
      worldIdB: 65535, xB: 0, yB: 0 }],
  );
  const save = extractSaveData(fake);
  assert.equal(save.worlds.length, 1);
  assert.equal(save.worlds[0].id, 23);
  assert.equal(save.portals.length, 2);
  assert.equal(save.portals[0].worldA, 12);
  assert.equal(save.portals[1].resolved, false);
  assert.equal(save.warnings.length, 1);
  assert.deepEqual(fake.bound()?.[0], WORLD_MARKER_UID);
});

test("world graph only joins real resolved references", () => {
  const worlds = [{ id: 12 }, { id: 23 }];
  const portals = [
    { worldA: 12, worldB: 23, resolved: true },
    { worldA: 12, worldB: 65535, resolved: false },
    { worldA: 12, worldB: 45, resolved: true },
  ];
  const graph = buildWorldGraph(worlds, portals);
  assert.equal(graph.edges.length, 1);
  assert.deepEqual([...graph.connected].sort((a,b) => a-b), [12, 23]);
  assert.equal(graph.missingWorldReferences, 1);
});

test("invalid file headers and unsupported schemas fail explicitly", () => {
  const valid = new Uint8Array(100);
  valid.set(encoder.encode("SQLite format 3"), 0);
  assertSqliteHeader(valid);
  assert.throws(() => assertSqliteHeader(encoder.encode("not sqlite")), /too small/);
  const corrupt = new Uint8Array(100);
  assert.throws(() => assertSqliteHeader(corrupt), /not a SQLite/);
  assert.throws(() => extractSaveData(mockDb(["Portal"], [], [])), /GenericData/);
});
