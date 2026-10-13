import test from "node:test";
import assert from "node:assert/strict";
import { reconstructPocketGroups } from "../pocket-groups.mjs";

const uuid = "034b98c5-c3ce-4fbc-b055-cd052d9864ca";
const asset = {name:"drill2_tunnelpocket_small_passage_15_2x2x2.tile",
  family:"tunnel_pocket", tags:["passage"],dimensions:[2,2,2]};

function pocket(x, y, sx, sy, width=16, depth=32, extra={}) {
  return {kind:"pocket",cellX:Math.floor(x/64),cellY:Math.floor(y/64),
    tileIndex:12,tileUuid:uuid,asset,rotation:0,sourceX:sx,sourceY:sy,
    x,y,z:0,width,depth,height:32,...extra};
}

test("two saved source fragments reconstruct one logical 2x2 pocket", () => {
  const footprints=[pocket(16,32,1,0),pocket(0,32,0,0)];
  const [group]=reconstructPocketGroups(footprints);
  assert.equal(group.id,1);
  assert.equal(group.fragmentCount,2);
  assert.deepEqual(group.fragments,[0,1]);
  assert.deepEqual([group.originChunkX,group.originChunkY], [0,2]);
  assert.deepEqual([group.x,group.y,group.width,group.depth,group.height],
    [0,32,32,32,32]);
  assert.equal(group.sourceOverlapChunks,0);
  assert.equal(group.sourceComplete,true);
  assert.equal(group.sizeMatches,true);
  assert.equal(group.complete,true);
  assert.equal(group.asset.name,asset.name);
});

test("adjacent identical pocket assets remain distinct when source origins differ", () => {
  const fragments=[
    pocket(0,0,0,0),pocket(16,0,1,0),
    pocket(32,0,0,0),pocket(48,0,1,0),
  ];
  const groups=reconstructPocketGroups(fragments);
  assert.equal(groups.length,2);
  assert.deepEqual(groups.map(g=>[g.originChunkX,g.fragmentCount,g.complete]),
    [[0,2,true],[2,2,true]]);
});

test("rotation transforms source fragments before deriving shared instance origin", () => {
  const wide = {...asset,dimensions:[3,2,2]};
  const input=[
    pocket(0,16,1,0,32,32,{rotation:1,asset:wide}),
    pocket(0,0,0,0,32,16,{rotation:1,asset:wide}),
  ];
  const [group]=reconstructPocketGroups(input);
  assert.equal(group.fragmentCount,2);
  assert.equal(group.complete,true);
  assert.deepEqual([group.originChunkX,group.originChunkY],[0,0]);
  assert.deepEqual([group.width,group.depth],[32,48]);
  // Another rotation uses inverse XY placement in saved chunk coordinates.
  const rotated180=[
    pocket(0,0,1,0,16,32,{rotation:2,asset}),
    pocket(16,0,0,0,16,32,{rotation:2,asset}),
  ];
  assert.equal(reconstructPocketGroups(rotated180).length,1);
  assert.equal(reconstructPocketGroups(rotated180)[0].complete,true);
});

test("missing source chunks and duplicate chunks cannot silently appear complete", () => {
  const [partial]=reconstructPocketGroups([pocket(0,0,0,0)]);
  assert.equal(partial.sourceComplete,false);
  assert.equal(partial.sizeMatches,false);
  assert.equal(partial.complete,false);
  const groups = reconstructPocketGroups([
    pocket(0,0,0,0), pocket(0,0,0,0),pocket(16,0,1,0),
  ]);
  assert.equal(groups[0].sourceOverlapChunks,2);
  assert.equal(groups[0].sourceComplete,true);
  assert.equal(groups[0].fragmentCount,3);
});

test("unknown asset identities remain ungrouped instead of inferring placements", () => {
  const pieces=[
    pocket(0,0,0,0,16,32,{tileUuid:null,asset:null}),
    pocket(16,0,1,0,16,32,{asset:null}),
    {kind:"cave",cellX:0,cellY:0},
  ];
  assert.deepEqual(reconstructPocketGroups(pieces),[]);
});
