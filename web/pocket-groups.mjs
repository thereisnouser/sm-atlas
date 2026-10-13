/**
 * Source-offset pocket reconstruction, ported from
 * sm_atlas.underground_pockets.reconstruct_logical_pockets.
 *
 * These are saved tile *placements*, not traversable volumes or doorways.
 * Only exact UUID-matched catalog assets with known dimensions are grouped.
 */

function rotatedSourceOffset(piece, sourceWidth, sourceDepth, tileWidth, tileDepth) {
  const x = piece.sourceX, y = piece.sourceY;
  switch (piece.rotation & 3) {
    case 1: return [tileDepth - (y + sourceDepth), x];
    case 2: return [tileWidth - (x + sourceWidth),
      tileDepth - (y + sourceDepth)];
    case 3: return [y, tileWidth - (x + sourceWidth)];
    default: return [x, y];
  }
}

function sourceFragmentSize(piece) {
  const worldWidth = Math.round(piece.width / 16);
  const worldDepth = Math.round(piece.depth / 16);
  return piece.rotation & 1
    ? [worldDepth, worldWidth] : [worldWidth, worldDepth];
}

export function reconstructPocketGroups(footprints) {
  const collected = new Map();
  for (const [index, piece] of footprints.entries()) {
    if (piece.kind !== "pocket"
      || !piece.tileUuid || !piece.asset?.dimensions
      || !Number.isInteger(piece.sourceX) || !Number.isInteger(piece.sourceY)) {
      continue;
    }
    const [tileWidth, tileDepth] = piece.asset.dimensions;
    const [sourceWidth, sourceDepth] = sourceFragmentSize(piece);
    const [offsetX, offsetY] = rotatedSourceOffset(
      piece, sourceWidth, sourceDepth, tileWidth, tileDepth);
    const originChunkX = Math.round(piece.x / 16) - offsetX;
    const originChunkY = Math.round(piece.y / 16) - offsetY;
    const key = [piece.tileUuid, piece.rotation, piece.z,
      originChunkX, originChunkY].join("|");
    if (!collected.has(key)) {
      collected.set(key, {
        tileUuid: piece.tileUuid, tileIndex: piece.tileIndex,
        asset: piece.asset, rotation: piece.rotation, z: piece.z,
        originChunkX, originChunkY, fragments: [],
      });
    }
    collected.get(key).fragments.push(index);
  }
  const groups = [...collected.values()].sort((a, b) =>
    a.z - b.z || a.originChunkY - b.originChunkY
    || a.originChunkX - b.originChunkX
    || a.tileUuid.localeCompare(b.tileUuid) || a.rotation - b.rotation);

  return groups.map((group, index) => {
    const pieces = group.fragments.map((i) => footprints[i]);
    const [tileWidth, tileDepth, tileHeight] = group.asset.dimensions;
    const expected = tileWidth * tileDepth;
    const covered = new Set();
    let overlap = 0;
    for (const piece of pieces) {
      const [w, d] = sourceFragmentSize(piece);
      for (let y = piece.sourceY; y < piece.sourceY + d; y++) {
        for (let x = piece.sourceX; x < piece.sourceX + w; x++) {
          const key = x + ":" + y;
          if (covered.has(key)) overlap++;
          covered.add(key);
        }
      }
    }
    let sourceComplete = covered.size === expected;
    if (sourceComplete) {
      for (let y = 0; y < tileDepth && sourceComplete; y++) {
        for (let x = 0; x < tileWidth; x++) {
          if (!covered.has(x + ":" + y)) {
            sourceComplete = false;
            break;
          }
        }
      }
    }
    const x = Math.min(...pieces.map((p) => p.x));
    const y = Math.min(...pieces.map((p) => p.y));
    const z = Math.min(...pieces.map((p) => p.z));
    const width = Math.max(...pieces.map((p) => p.x + p.width) - x;
    const depth = Math.max(...pieces.map((p) => p.y + p.depth) - y;
    const height = Math.max(...pieces.map((p) => p.z + p.height) - z;
    const expectedWidth = (group.rotation & 1 ? tileDepth : tileWidth) * 16;
    const expectedDepth = (group.rotation & 1 ? tileWidth : tileDepth) * 16;
    const expectedHeight = tileHeight * 16;
    const sizeMatches = width === expectedWidth
      && depth === expectedDepth && height === expectedHeight;
    return {
      id: index + 1, ...group, fragmentCount: group.fragments.length,
      x, y, z, width, depth, height, sourceComplete,
      sourceOverlapChunks: overlap, sizeMatches,
      complete: sourceComplete && sizeMatches,
    };
  });
}
