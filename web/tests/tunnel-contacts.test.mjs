import test from "node:test";
import assert from "node:assert/strict";
import {segmentTouchesFootprint,analyzeTunnelPlacementContacts}
  from "../tunnel-contacts.mjs";

const box={kind:"cave",x:0,y:0,z:0,width:16,depth:16,height:16};
const line=(...points)=>({points});

test("3D slab distinguishes true bounding-box touches from XY-only overlaps",()=>{
  assert.equal(segmentTouchesFootprint([-10,8,8],[24,8,8],box),true);
  assert.equal(segmentTouchesFootprint([-10,8,48],[24,8,48],box),false);
  assert.equal(segmentTouchesFootprint([-10,8,48],[24,8,48],box,false),true);
  assert.equal(segmentTouchesFootprint([-10,-1,8],[24,-1,8],box,false),false);
  assert.equal(segmentTouchesFootprint([-4,8,-8],[8,8,8],box),true);
  assert.equal(segmentTouchesFootprint([8,8,48],[8,8,24],box),false);
  assert.equal(segmentTouchesFootprint([0,0,0],[0,0,0],box),true);
  assert.equal(segmentTouchesFootprint([-1,0,0],[0,0,0],box),true);
  assert.equal(segmentTouchesFootprint([-1,0,0],[-0.1,0,0],box),false);
});

test("invalid boxes, coordinates and degenerate dimensions cannot create evidence",()=>{
  assert.equal(segmentTouchesFootprint([0,0,0],[2,2,2],{...box,width:0}),false);
  assert.equal(segmentTouchesFootprint([0,0,0],[2,2,2],{...box,z:NaN}),false);
  assert.equal(segmentTouchesFootprint([0,0,0],[Infinity,2,2],box),false);
  assert.equal(segmentTouchesFootprint([0,0,0],[2,2,2],{...box,depth:-1}),false);
});

test("logical placement contacts are distinct across split fragments and Z",()=>{
  const pieces=[
    {...box,x:0,width:16},
    {...box,x:16,width:16},
    {...box,x:40,z:40,width:16},
    {...box,x:56,z:40,width:16},
    {...box,x:75,z:0,width:8},
  ];
  const hit=analyzeTunnelPlacementContacts(
    line([-8,8,8],[95,8,8]),pieces,
    [{id:1,fragments:[0,1]},{id:2,fragments:[2,3]}],[]);
  assert.deepEqual(hit.xyzIndices,[0,1,4]);
  assert.deepEqual(hit.xyOnlyIndices,[2,3]);
  assert.deepEqual(hit.xyzPlacements,["Cave group G1","Unidentified cave tile #undefined"]);
  assert.deepEqual(hit.xyOnlyPlacements,["Cave group G2"]);
});

test("mixed group touching in XYZ and XY-only is counted once as XYZ",()=>{
  const pieces=[{...box},{...box,x:16,z:32}];
  const hit=analyzeTunnelPlacementContacts(line([-2,8,8],[40,8,8]),
    pieces,[],[{id:3,fragments:[0,1],asset:{name:"split_asset.tile"}}]);
  assert.deepEqual(hit.xyzIndices,[0]);
  assert.deepEqual(hit.xyOnlyIndices,[1]);
  assert.deepEqual(hit.xyzPlacements,["split_asset.tile"]);
  assert.deepEqual(hit.xyOnlyPlacements,[]);
  assert.deepEqual(analyzeTunnelPlacementContacts(line([0,0,0]),pieces),{
    xyzIndices:[],xyOnlyIndices:[],xyzPlacements:[],xyOnlyPlacements:[],
  });
});
