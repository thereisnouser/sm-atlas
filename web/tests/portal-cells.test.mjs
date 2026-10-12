import test from "node:test";
import assert from "node:assert/strict";
import {
  UNDERGROUND_CELL_SIZE, portalCellsForWorld, portalCellOverlapsPlacement,
} from "../portal-cells.mjs";

test("known saved portal side is mapped to an entire 64-unit grid cell", () => {
  const portals = [
    {id: 64, worldA: 12, xA: -2, yA: 2, worldB: 21, xB: 0, yB: 0, resolved: true},
    {id: 67, worldA: 12, xA: -2, yA: 2, worldB: 23, xB: 0, yB: 0, resolved: true},
  ];
  assert.equal(UNDERGROUND_CELL_SIZE, 64);
  assert.deepEqual(portalCellsForWorld(portals, 21), [{
    portalId: 64, sides: "B", cellX: 0, cellY: 0,
    x: 0, y: 0, width: 64, depth: 64, otherWorldId: 12, linked: true,
  }]);
  assert.deepEqual(portalCellsForWorld(portals, 12).map(p => [
    p.portalId, p.cellX, p.cellY, p.x, p.y,
  ]), [[64, -2, 2, -128, 128], [67, -2, 2, -128, 128]]);
});

test("unresolved sides are not plotted in nonexistent world 65535", () => {
  const portals = [
    {id: 17, worldA: 23, xA: 4, yA: -3,
      worldB: 65535, xB: 0, yB: 0, resolved: false},
  ];
  assert.deepEqual(portalCellsForWorld(portals, 65535), []);
  assert.deepEqual(portalCellsForWorld(portals, 23), [{
    portalId: 17, sides: "A", cellX: 4, cellY: -3, x: 256, y: -192,
    width: 64, depth: 64, otherWorldId: null, linked: false,
  }]);
});

test("same-world portal endpoints are preserved without duplicate same-cell markers", () => {
  const portals = [
    {id: 65, worldA: 22, xA: 0, yA: 2, worldB: 22, xB: 0, yB: 2,
      resolved: true},
    {id: 66, worldA: 22, xA: -1, yA: 5, worldB: 22, xB: 3, yB: 6,
      resolved: true},
  ];
  const cells = portalCellsForWorld(portals, 22);
  assert.equal(cells.length, 3);
  assert.equal(cells[0].sides, "A/B");
  assert.equal(cells[0].otherWorldId, 22);
  assert.deepEqual(cells.slice(1).map(p => [p.cellX, p.cellY]), [[-1, 5], [3, 6]]);
});

test("portal grid overlap reports cell placement, never actual doorway geometry", () => {
  const [cell] = portalCellsForWorld([
    {id: 8, worldA: 23, xA: 0, yA: 0, worldB: 12, xB: -2, yB: 2,
      resolved: true},
  ], 23);
  assert.equal(portalCellOverlapsPlacement(cell, [
    {kind: "cave", cellX: 0, cellY: 0, x: 0, y: 0, width: 64, depth: 64},
  ]), true);
  assert.equal(portalCellOverlapsPlacement(cell, [
    {kind: "cave", cellX: 0, cellY: -1},
  ]), false);
  assert.equal(portalCellOverlapsPlacement(cell, null), false);
});

test("nonintegral, invalid portal endpoints are not plotted", () => {
  assert.deepEqual(portalCellsForWorld([{id: 1, worldA: 23, xA: 1.5, yA: 0,
    worldB: 13, xB: 0, yB: 0}], 23), []);
});
