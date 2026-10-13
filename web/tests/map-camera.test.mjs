import test from "node:test";
import assert from "node:assert/strict";
import { FULL_MAP_VIEW, MAX_MAP_ZOOM, zoomMapView, panMapView,
  mapZoomPercent } from "../map-camera.mjs";

test("zoom is anchored to the cursor without distorting map proportions", () => {
  const view = zoomMapView(FULL_MAP_VIEW, 2, 0.25, 0.75);
  assert.deepEqual(view, {x:125, y:232.5, width:500, height:310});
  assert.equal(mapZoomPercent(view), 200);
  assert.deepEqual(zoomMapView(view, 0.5, 0.25, 0.75), FULL_MAP_VIEW);
});

test("zoom limits prevent lost maps or unbounded view-box sizes", () => {
  const tiny = zoomMapView(FULL_MAP_VIEW, 100000);
  assert.equal(tiny.width, 1000 / MAX_MAP_ZOOM);
  assert.equal(tiny.height, 620 / MAX_MAP_ZOOM);
  assert.equal(mapZoomPercent(tiny), 1600);
  assert.deepEqual(zoomMapView(tiny, 0.000001), FULL_MAP_VIEW);
});

test("panning stays within the world overview and does not mutate prior state", () => {
  const start = zoomMapView(FULL_MAP_VIEW, 4);
  const moved = panMapView(start, 50000, -50000);
  assert.deepEqual(moved, {x:750, y:0, width:250, height:155});
  assert.deepEqual(panMapView(moved, -50000, 50000),
    {x:0, y:465, width:250, height:155});
  assert.deepEqual(start, {x:375, y:232.5, width:250, height:155});
});

test("invalid zoom/pan input and out-of-bounds anchors are harmless", () => {
  assert.equal(zoomMapView(FULL_MAP_VIEW, NaN), FULL_MAP_VIEW);
  assert.equal(zoomMapView(FULL_MAP_VIEW, -2), FULL_MAP_VIEW);
  assert.equal(panMapView(FULL_MAP_VIEW, Infinity, 0), FULL_MAP_VIEW);
  const corner = zoomMapView(FULL_MAP_VIEW, 2, 2, -1);
  assert.deepEqual(corner, {x:500, y:0, width:500, height:310});
});
