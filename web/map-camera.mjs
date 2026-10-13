/** Bounded viewport transformations over the 1000x620 saved-layout SVG.
 * These functions change the viewport only, never the saved game coordinates.
 */
export const FULL_MAP_VIEW = Object.freeze({ x: 0, y: 0, width: 1000, height: 620 });
export const MAX_MAP_ZOOM = 16;

function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value));
}

export function zoomMapView(view, factor, anchorX = 0.5, anchorY = 0.5) {
  if (!Number.isFinite(factor) || factor <= 0) return view;
  const ax = clamp(Number.isFinite(anchorX) ? anchorX : 0.5, 0, 1);
  const ay = clamp(Number.isFinite(anchorY) ? anchorY : 0.5, 0, 1);
  const nextWidth = clamp(view.width / factor,
    FULL_MAP_VIEW.width / MAX_MAP_ZOOM, FULL_MAP_VIEW.width);
  const nextHeight = FULL_MAP_VIEW.height * (nextWidth / FULL_MAP_VIEW.width);
  const nextX = view.x + (view.width - nextWidth) * ax;
  const nextY = view.y + (view.height - nextHeight) * ay;
  return {
    x: clamp(nextX, FULL_MAP_VIEW.x,
      FULL_MAP_VIEW.x + FULL_MAP_VIEW.width - nextWidth),
    y: clamp(nextY, FULL_MAP_VIEW.y,
      FULL_MAP_VIEW.y + FULL_MAP_VIEW.height - nextHeight),
    width: nextWidth, height: nextHeight,
  };
}

export function panMapView(view, deltaX, deltaY) {
  if (![deltaX, deltaY].every(Number.isFinite)) return view;
  return {
    ...view,
    x: clamp(view.x + deltaX, FULL_MAP_VIEW.x,
      FULL_MAP_VIEW.x + FULL_MAP_VIEW.width - view.width),
    y: clamp(view.y + deltaY, FULL_MAP_VIEW.y,
      FULL_MAP_VIEW.y + FULL_MAP_VIEW.height - view.height),
  };
}

export function mapZoomPercent(view) {
  return Math.round(100 * FULL_MAP_VIEW.width / view.width);
}
