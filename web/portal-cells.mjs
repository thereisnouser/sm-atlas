/**
 * Saved Portal-table endpoint cells for the underground map.
 *
 * Portal.xA/yA and xB/yB are grid-cell indices. The underground placement
 * grid uses 64 saved XY units per cell. Drawing these as whole CELL AREAS
 * is a coordinate-system hypothesis, NOT a precise entrance or a path.
 * A matched tile placement is evidence of grid overlap, not accessibility.
 */
export const UNDERGROUND_CELL_SIZE = 64;

export function portalCellsForWorld(portals, worldId) {
  if (!Number.isSafeInteger(worldId) || worldId < 0 || worldId === 65535) return [];
  const collected = [];
  for (const portal of portals) {
    if (!Number.isSafeInteger(portal.id)) continue;
    const a = portal.worldA === worldId;
    const b = portal.worldB === worldId;
    for (const side of ["A", "B"]) {
      if ((side === "A" && !a) || (side === "B" && !b)) continue;
      const x = side === "A" ? portal.xA : portal.xB;
      const y = side === "A" ? portal.yA : portal.yB;
      if (!Number.isSafeInteger(x) || !Number.isSafeInteger(y)) continue;
      const other = side === "A" ? portal.worldB : portal.worldA;
      const otherWorldId = Number.isSafeInteger(other) && other !== 65535
        ? other : null;
      const existing = collected.find((item) =>
        item.portalId === portal.id && item.cellX === x && item.cellY === y);
      if (existing) {
        existing.sides += "/" + side;
      } else {
        collected.push({
          portalId: portal.id, sides: side, cellX: x, cellY: y,
          x: x * UNDERGROUND_CELL_SIZE,
          y: y * UNDERGROUND_CELL_SIZE,
          width: UNDERGROUND_CELL_SIZE,
          depth: UNDERGROUND_CELL_SIZE,
          otherWorldId, linked: portal.resolved === true,
        });
      }
    }
  }
  collected.sort((a, b) =>
    a.portalId - b.portalId || a.cellX - b.cellX || a.cellY - b.cellY);
  return collected;
}

export function portalCellOverlapsPlacement(cell, footprints) {
  if (!Array.isArray(footprints)) return false;
  return footprints.some((piece) =>
    Number.isFinite(piece.cellX) && Number.isFinite(piece.cellY)
    && piece.cellX === cell.cellX && piece.cellY === cell.cellY);
}
