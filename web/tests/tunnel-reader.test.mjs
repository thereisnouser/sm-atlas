import test from "node:test";
import assert from "node:assert/strict";
import initSqlJs from "sql.js";
import { identifyTile, tileCatalogSize } from "../tile-catalog.mjs";
import {
  decodeLuaValue, decodeScriptDataRecord,
  extractSavedTunnels, extractSavedFootprints, reconstructCaveGroups, extractTerrainTunnels,
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
    ["caves", (t) => t.table([
      [-2, (row) => row.table([
        [4, (cell) => cell.table([
          [1, (v) => v.integer(
            7 | (2 << 8) | (2 << 12) | (1 << 16) | (2 << 18) | (1 << 20)
          )],
        ])],
      ])],
    ])],
    ["pockets", (t) => t.table([
      [3, (row) => row.table([
        [-1, (cell) => cell.table([
          [1, (v) => v.integer(
            9 | (0x56 << 8) | (0x39 << 16) | (1 << 28)
          )],
        ])],
      ])],
    ])],
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
  const footprints = extractSavedFootprints(value);
  assert.equal(footprints.length, 2);
  assert.deepEqual(footprints[0], {
    kind: "cave", cellX: 4, cellY: -2, tileIndex: 7, tileUuid: null, asset: null, rotation: 1,
    x: 256, y: -128, z: 32, width: 64, depth: 64, height: 48,
  });
  assert.deepEqual(footprints[1], {
    kind: "pocket", cellX: -1, cellY: 3, tileIndex: 9, tileUuid: null, asset: null, rotation: 1,
    x: -32, y: 208, z: 80, width: 48, depth: 32, height: 64,
  });
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
    assert.equal(res.footprints.length, 2);
    assert.equal(res.caveGroups.length, 1);
    assert.equal(res.caveGroups[0].identityVerified, false);
    assert.equal(res.footprints[0].kind, "cave");
    assert.equal(res.footprints[1].kind, "pocket");
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

test("malformed placement grids cannot create fictitious cave footprints", () => {
  const value = new Map([
    ["caves", new Map([[0, new Map([
      [1, new Map([[0, true], [1, "not a packed cell"]])],
      [2, null],
    ])]])],
    ["pockets", new Map([["not an integer row", new Map()]])],
  ]);
  assert.deepEqual(extractSavedFootprints(value), []);
});


test("six adjacent cave cells form one logical placement, matching Python grouping", () => {
  const cave = (x,y,rest={}) => ({
    kind:"cave",cellX:x,cellY:y,tileIndex:1,
    tileUuid:"52b1c24b-befd-41a6-95c4-54d697737fa6",
    rotation:0,x:x*64,y:y*64,z:0,width:64,depth:64,height:128,
    ...rest,
  });
  const parts = Array.from({length:2}, (_,y) =>
    Array.from({length:3},(_,x)=>cave(10+x,-5+y))).flat().reverse();
  const groups = reconstructCaveGroups(parts);
  assert.equal(groups.length,1);
  assert.equal(groups[0].fragmentCount,6);
  assert.equal(groups[0].identityVerified,true);
  assert.equal(groups[0].tileUuid,"52b1c24b-befd-41a6-95c4-54d697737fa6");
  assert.deepEqual([groups[0].x,groups[0].y,groups[0].width,
    groups[0].depth,groups[0].height],[640,-320,192,128,128]);
  assert.deepEqual(groups[0].fragments.slice().sort((a,b)=>a-b),[0,1,2,3,4,5]);
});

test("adjacent but different tiles, rotations or Z do not merge into fictional rooms",()=>{
  const a={kind:"cave",cellX:0,cellY:0,tileIndex:1,tileUuid:null,
    rotation:0,z:16,x:0,y:0,width:64,depth:64,height:16};
  const parts=[
    a,
    {...a,cellX:1,x:64}, // joins a
    {...a,cellX:2,x:128,tileIndex:2}, // not same tile index
    {...a,cellX:0,cellY:1,y:64,rotation:1}, // different rotation
    {...a,cellX:0,cellY:-1,y:-64,z:32}, // different height
    {...a,cellX:0,cellY:0,x:0,y:0,kind:"pocket"}, // never joins caves
    {...a,cellX:20,x:1280}, // separate
  ];
  const groups=reconstructCaveGroups(parts);
  assert.equal(groups.length,5);
  assert.deepEqual(groups.map(g=>g.fragmentCount).sort((a,b)=>a-b),[1,1,1,1,2]);
  assert.equal(groups.every(g=>g.identityVerified===false),true);
  assert.equal(groups.some(g=>g.tileIndex===2&&g.fragmentCount===1),true);
});

test("saved tileList UUIDs are byte-reversed and keep equal indexes distinguishable",()=>{
  const uuid=Uint8Array.from({length:16},(_,i)=>i);
  const value=new Map([
    ["tileList",new Map([[7,{type:"uuid",bytes:uuid}]])],
    ["caves",new Map([[0,new Map([[2,new Map([[1,7]])]])]])],
  ]);
  const footprints=extractSavedFootprints(value);
  assert.equal(footprints.length,1);
  assert.equal(footprints[0].tileUuid,"0f0e0d0c-0b0a-0908-0706-050403020100");
  const other={...footprints[0],cellX:3,x:192,tileUuid:null};
  assert.equal(reconstructCaveGroups([...footprints,other]).length,2);
});


test("known metadata comes from exact asset UUID, not guessed tile index", () => {
  assert.equal(tileCatalogSize, 193);
  const elevator = identifyTile("52b1c24b-befd-41a6-95c4-54d697737fa6");
  assert.equal(elevator.name, "drill2_elevator_12x8x8.tile");
  assert.equal(elevator.family, "elevator");
  assert.deepEqual(elevator.dimensions, [12,8,8]);
  assert.deepEqual(elevator.tags, ["elevator"]);
  const passage = identifyTile("034b98c5-c3ce-4fbc-b055-cd052d9864ca");
  assert.equal(passage.family, "tunnel_pocket");
  assert.equal(passage.tags.includes("passage"), true);
  assert.equal(identifyTile("ffffffff-ffff-ffff-ffff-ffffffffffff"), null);
  assert.equal(identifyTile(null), null);
});

test("catalog checks expected fragment count and rotated dimensions independently", () => {
  const uuid = "52b1c24b-befd-41a6-95c4-54d697737fa6";
  const make = (x,y,rotation=0) => ({
    kind:"cave",cellX:x,cellY:y,x:x*64,y:y*64,z:0,
    height:128,width:64,depth:64,rotation,tileIndex:1,tileUuid:uuid,
  });
  const six = Array.from({length:2},(_,y)=>
    Array.from({length:3},(_,x)=>make(10+x,5+y))).flat();
  const [complete] = reconstructCaveGroups(six);
  assert.equal(complete.asset.name, "drill2_elevator_12x8x8.tile");
  assert.equal(complete.asset.family, "elevator");
  assert.equal(complete.expectedFragments,6);
  assert.equal(complete.countMatches,true);
  assert.equal(complete.sizeMatches,true);
  const [missing] = reconstructCaveGroups(six.slice(0,3));
  assert.equal(missing.fragmentCount,3);
  assert.equal(missing.countMatches,false);
  assert.equal(missing.sizeMatches,false);
  // A 90-degree rotation swaps the expected XY dimensions.
  const rotated = Array.from({length:3},(_,y)=>
    Array.from({length:2},(_,x)=>make(10+x,5+y,1))).flat();
  const [other] = reconstructCaveGroups(rotated);
  assert.equal(other.countMatches,true);
  assert.equal(other.sizeMatches,true);
});

test("known saved tile UUID references resolve from reversed Lua UUID bytes", () => {
  const uuid="034b98c5-c3ce-4fbc-b055-cd052d9864ca";
  const hex=uuid.replaceAll("-","");
  const diskBytes=Uint8Array.from(hex.match(/../g).map(x=>parseInt(x,16)).reverse());
  const value=new Map([
    ["tileList",new Map([[12,{type:"uuid",bytes:diskBytes}]])],
    ["pockets",new Map([[0,new Map([[0,new Map([[1,12]])]])]])],
  ]);
  const [piece]=extractSavedFootprints(value);
  assert.equal(piece.tileUuid,uuid);
  assert.equal(piece.asset.name,"drill2_tunnelpocket_small_passage_15_2x2x2.tile");
  assert.equal(piece.asset.tags.includes("passage"),true);
  assert.equal(piece.kind,"pocket");
});
