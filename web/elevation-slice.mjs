/**
 * Evidence-only elevation slicing for recorded tunnel centerlines and
 * rectangular tile placements. Z here is a saved-world coordinate, not
 * validated cave-floor height, clearance or a navigable route.
 */
export const ELEVATION_STEP = 16;

export function elevationBand(index) {
  if (!Number.isSafeInteger(index)) return null;
  return {low: index * ELEVATION_STEP, high: (index + 1) * ELEVATION_STEP};
}

export function availableElevationBands(tunnels = [], footprints = []) {
  let low = Infinity, high = -Infinity;
  for (const tunnel of tunnels) {
    for (const point of tunnel.points || []) {
      const z = point[2];
      if (!Number.isFinite(z)) continue;
      low = Math.min(low, Math.floor(z / ELEVATION_STEP));
      high = Math.max(high, Math.floor(z / ELEVATION_STEP));
    }
  }
  for (const piece of footprints) {
    if (!Number.isFinite(piece.z) || !Number.isFinite(piece.height)
      || piece.height <= 0) continue;
    low = Math.min(low, Math.floor(piece.z / ELEVATION_STEP));
    high = Math.max(high, Math.ceil((piece.z + piece.height) / ELEVATION_STEP) - 1);
  }
  if (low === Infinity || high === -Infinity || !Number.isSafeInteger(low)
    || !Number.isSafeInteger(high) || high - low > 4096) return null;
  return {min:low, max:high};
}

export function placementOverlapsBand(piece, band) {
  return !band || (Number.isFinite(piece?.z) && Number.isFinite(piece?.height)
    && piece.height > 0 && piece.z < band.high
    && piece.z + piece.height > band.low);
}

function clipSegment(a, b, band) {
  if (![...a, ...b].every(Number.isFinite)) return null;
  const dz = b[2] - a[2];
  if (dz === 0) {
    return a[2] >= band.low && a[2] < band.high ? [a,b] : null;
  }
  const z0 = (band.low - a[2]) / dz;
  const z1 = (band.high - a[2]) / dz;
  const start = Math.max(0, Math.min(z0, z1));
  const end = Math.min(1, Math.max(z0, z1));
  if (end <= start) return null;
  const at = (t) => a.map((value,i) => value + (b[i] - value) * t);
  return [at(start), at(end)];
}

const samePoint = (a,b) => a.every((value,i) =>
  Math.abs(value - b[i]) < 1e-8);

/** Return contiguous XY/Z polylines, clipping crossing segments exactly. */
export function visibleTunnelPaths(points, band) {
  if (!Array.isArray(points) || points.length < 2) return [];
  if (!band) return [points];
  const paths = [];
  let current = [];
  const flush = () => {
    if (current.length >= 2) paths.push(current);
    current = [];
  };
  for (let i = 1; i < points.length; i++) {
    const clipped = clipSegment(points[i - 1], points[i], band);
    if (!clipped) {
      flush();
    } else if (current.length && samePoint(current[current.length - 1], clipped[0])) {
      current.push(clipped[1]);
    } else {
      flush();
      current = clipped;
    }
  }
  flush();
  return paths;
}
