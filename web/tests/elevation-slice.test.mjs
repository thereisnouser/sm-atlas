import test from "node:test";
import assert from "node:assert/strict";
import { availableElevationBands, elevationBand, placementOverlapsBand,
  visibleTunnelPaths } from "../elevation-slice.mjs";

test("saved Z bands include negative heights, exact top bounds and missing geometry", () => {
  assert.deepEqual(availableElevationBands([
    {points:[[0,0,-1],[1,0,16]]},
  ],[
    {z:0,height:16},
    {z:16,height:32},
  ]),{min:-1,max:2});
  assert.equal(availableElevationBands([],[]),null);
  assert.equal(availableElevationBands([],[{z:5,height:0}]),null);
  assert.equal(availableElevationBands([],[{z:0,height:1000000}]),null);
  assert.deepEqual(elevationBand(-1),{low:-16,high:0});
  assert.equal(elevationBand(1.5),null);
});

test("placement overlaps only bands containing saved Z extent", () => {
  const cave={z:16,height:32};
  assert.equal(placementOverlapsBand(cave,null),true);
  assert.equal(placementOverlapsBand(cave,elevationBand(0)),false);
  assert.equal(placementOverlapsBand(cave,elevationBand(1)),true);
  assert.equal(placementOverlapsBand(cave,elevationBand(2)),true);
  assert.equal(placementOverlapsBand(cave,elevationBand(3)),false);
  assert.equal(placementOverlapsBand({z:0,height:0},elevationBand(0)),false);
});

test("crossing tunnel segments are clipped instead of appearing at wrong elevation",()=>{
  const points=[[0,0,0],[32,0,32]];
  const paths=visibleTunnelPaths(points,elevationBand(0));
  assert.deepEqual(paths,[[[0,0,0],[16,0,16]]]);
  assert.deepEqual(visibleTunnelPaths(points,elevationBand(1)),
    [[[16,0,16],[32,0,32]]]);
  assert.deepEqual(visibleTunnelPaths(points,elevationBand(3)),[]);
  assert.deepEqual(visibleTunnelPaths(points,null),[points]);
});

test("polyline never bridges hidden gaps or disconnected elevations",()=>{
  const points=[
    [0,0,0],[4,0,8],[8,0,32],[12,0,32],[16,0,8],[20,0,0],
  ];
  const paths=visibleTunnelPaths(points,elevationBand(0));
  assert.equal(paths.length,2);
  assert.deepEqual(paths[0],[[0,0,0],[4,0,8],[16/3,0,16]]);
  assert.deepEqual(paths[1],[[44/3,0,16],[16,0,8],[20,0,0]]);
});

test("a horizontal Z boundary does not bleed into a neighboring band",()=>{
  assert.deepEqual(visibleTunnelPaths([[0,0,16],[5,0,16]],elevationBand(0)),[]);
  assert.equal(visibleTunnelPaths([[0,0,16],[5,0,16]],elevationBand(1)).length,1);
  assert.deepEqual(visibleTunnelPaths([[0,0,-16],[5,0,0]],elevationBand(-1)),
    [[[0,0,-16],[5,0,0]]]);
});
