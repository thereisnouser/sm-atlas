import test from "node:test";
import assert from "node:assert/strict";
import initSqlJs from "sql.js";
import {
  decodeLuaValue, decodeScriptDataRecord,
  extractSavedTunnels, extractTerrainTunnels,
} from "../tunnel-reader.mjs";

class Writer {
  bits = [];
  write(n, count) {
    for (let bit = count - 1; bit >= 0; bit--) this.bits.push((n >>> bit) & 1);
  }
  bytes(data) { for (const byte of data) this.write(byte, 8); }
  align() { while (this.bits.length % 8) this.bits.push(0); }
  string(str) {
    const bytes = new TextEncoder().encode(str);
    this.write(4, 8);
    this.write(bytes.length, 32);
    this.align();
    this.bytes(bytes);
  }
  integer(n) { this.write(6, 8); this.write(n, 32); }
  vec3(x, y, z) {
    this.write(0x64, 8);
    this.write(10003, 32);
    const view = new DataView(new ArrayBuffer(4));
    for (const n of [x, y, z]) {
      view.setFloat32(0, n, false);
      this.write(view.getUint32(0, false), 32);
    }
  }
  table(pairs) {
    this.write(5, 8);
    this.write(pairs.length, 32);
    this.write(0, 1);
    for (const [key, value] of pairs) {
      if (typeof key === "number") this.integer(key);
      else this.string(key);
      if (typeof value === "function") value(this);
      else if (typeof value === "string") this.string(value);
      else throw Error("Invalid test fixture");
    }
  }
  finish() {
    this.align();
    const result = new Uint8Array(this.bits.length / 8);
    for (let i = 0; i < result.length; i++) {
      for (let bit = 0; bit < 8; bit++) result[i] = result[i] * 2 + this.bits[i*8+bit];
    }
    return result;
  }
}
function makeTerrainLua() {
  const w = new Writer();
  w.bytes(Uint8Array.from([76,85,65])); w.write(1,32);
  w.table([
    ["tunnels", (t) => t.table([
      [17, (u) => u.table([
        ["tunnelType", "TtVeinT4"],
        ["positions", (p) => p.table([
          [1, (v) => v.vec3(0,0,0)],
          [2, (v) => v.vec3(3,4,0)],
          [3, (v) => v.vec3(3,4,12)],
        ])],
      ])],
    ])],
    ["bounds", (t) => t.table([])],
  ]);
  return w.finish();
}
function join(...parts) {
  const bytes = new Uint8Array(parts.reduce((s,p)=>s+p.length,0));
  let offset = 0;
  for (const part of parts) { bytes.set(part, offset); offset += part.length; }
  return bytes;
}
function be(n,size) {return Uint8Array.from(
  Array.from({length:size},(_,i)=>(n >>> ((size-i-1)*8)) & 255)); }
function literalLz4(raw) {
  const prefix=[Math.min(raw.length,15)<<4];
  if (raw.length>=15) {
    let n=raw.length-15;
    while(n>=255) { prefix.push(255);n-=255; }
    prefix.push(n);
  }
  return join(Uint8Array.from(prefix), raw);
}
function envelope(raw,worldId=23) {
  const compressed=literalLz4(raw);
  return join(new Uint8Array(16),be(3,2),
    Uint8Array.from([1,2,3]),be(worldId,2),
    Uint8Array.from([7]),be(compressed.length,4),compressed);
}
test("Lua binary maps preserve numeric tunnel IDs and bit-packed Vec3 coordinates",()=>{
  const value=decodeLuaValue(makeTerrainLua());
  assert.equal(value.get("bounds") instanceof Map,true);
  const tunnels=extractSavedTunnels(value);
  assert.equal(tunnels.length,1);
  assert.equal(tunnels[0].id,17);
  assert.equal(tunnels[0].type,"TtVeinT4");
  assert.deepEqual(tunnels[0].points,[[0,0,0],[3,4,0],[3,4,12]]);
  assert.equal(tunnels[0].length,17);
});
test("ScriptData envelope validates embedded world ID and compressed byte length",()=>{
  const blob=envelope(makeTerrainLua());
  assert.ok(decodeScriptDataRecord(blob,23).rawSize>20);
  assert.throws(()=>decodeScriptDataRecord(blob,12),/world ID mismatch/);
  assert.throws(()=>decodeScriptDataRecord(blob.subarray(0,blob.length-1),23),
    /compressed payload length/);
  assert.throws(()=>decodeLuaValue(Uint8Array.from([1,2,3])),/LUA record header/);
});
test("browser SQLite extracts a genuine saved-terrain record without external files",async()=>{
  const SQL=await initSqlJs();
  const db=new SQL.Database();
  try {
    db.run("CREATE TABLE ScriptData(worldId INTEGER, data BLOB)");
    db.run("INSERT INTO ScriptData VALUES(?,?)",[23,envelope(makeTerrainLua())]);
    db.run("INSERT INTO ScriptData VALUES(?,?)",[23,Uint8Array.from([1,2])]);
    const res=extractTerrainTunnels(db,23);
    assert.equal(res.status,"available");
    assert.equal(res.tunnels.length,1);
    assert.equal(res.tunnels[0].length,17);
    assert.equal(res.failed,1);
    assert.equal(res.scanned,2);
    assert.equal(extractTerrainTunnels(db,12).status,"unavailable");
  }finally{db.close();}
});
test("missing terrain and missing tunnel coordinates are clearly unavailable",async()=>{
  const SQL=await initSqlJs();
  const db=new SQL.Database();
  try{
    assert.equal(extractTerrainTunnels(db,23).status,"no-script-data");
    assert.deepEqual(extractSavedTunnels(new Map([["tunnels",new Map()]])),[]);
  }finally{db.close();}
});
