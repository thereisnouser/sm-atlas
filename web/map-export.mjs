/**
 * Standalone, local-only export of the currently visible SVG map.
 * Copies computed SVG paint properties, not web-page CSS or game save bytes.
 * The current viewport is clipped before adding the permanent evidence note.
 */
const NS = "http://www.w3.org/2000/svg";
const PAINT = [
  "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width",
  "stroke-opacity", "stroke-dasharray", "stroke-dashoffset",
  "stroke-linecap", "stroke-linejoin", "opacity", "vector-effect",
  "paint-order", "font-family", "font-size", "font-weight", "text-anchor",
];

function svg(name, attrs = {}, text = null) {
  const node = document.createElementNS(NS, name);
  for (const [key,value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  if (text !== null) node.textContent = text;
  return node;
}

export function standaloneMapSvg(source, {worldLabel, heightLabel} = {}) {
  if (!(source instanceof SVGSVGElement)) throw new TypeError("SVG map required");
  // Source is created solely by the Atlas renderer; reject unrelated embedded
  // content rather than exporting scripts, remote images, or external links.
  if (source.querySelector("script, foreignObject, image, use, a, animate, set")) {
    throw new Error("Unexpected embedded SVG content");
  }
  const view = source.viewBox.baseVal;
  const {x,y,width,height} = view;
  if (![x,y,width,height].every(Number.isFinite) || width <= 0 || height <= 0) {
    throw new Error("Invalid current map viewport");
  }

  const copy = source.cloneNode(true);
  const originals = [source, ...source.querySelectorAll("*")];
  const clones = [copy, ...copy.querySelectorAll("*")];
  for (let index = 0; index < originals.length; index++) {
    const computed = getComputedStyle(originals[index]);
    for (const property of PAINT) {
      const value = computed.getPropertyValue(property);
      if (value) clones[index].style.setProperty(property, value);
    }
  }
  // Nested SVG clips geometry outside the selected zoom/pan view. Without
  // this, off-screen lines could extend into the exported footer.
  copy.removeAttribute("id");
  copy.setAttribute("x", String(x));
  copy.setAttribute("y", String(y));
  copy.setAttribute("width", String(width));
  copy.setAttribute("height", String(height));
  copy.setAttribute("overflow", "hidden");

  const footHeight = width * 0.11;
  const font = width * 0.017;
  const root = svg("svg", {
    xmlns:NS, version:"1.1", width:1600,
    height:Math.round(1600 * (height + footHeight) / width),
    viewBox:[x,y,width,height+footHeight].join(" "),
    "aria-label":"SM Atlas saved underground map snapshot",
  });
  root.append(svg("title", {}, "SM Atlas · saved underground map"));
  root.append(svg("desc", {}, "Recorded tunnel centerlines and tile allocation "
    + "bounds, not verified cave interiors, entrances or walkable routes."));
  root.append(svg("rect", {
    x,y,width,height:height+footHeight,fill:"#101923",
  }),copy);
  root.append(svg("rect", {
    x,y:y+height,width,height:footHeight,fill:"#1b2a36",
  }));
  const label = String(worldLabel || "Underground world").slice(0,55);
  const level = String(heightLabel || "All saved heights").slice(0,50);
  root.append(svg("text", {
    x:x+width*0.018,y:y+height+footHeight*0.34,
    fill:"#e2f4f8","font-family":"sans-serif","font-size":font,
    "font-weight":"700",
  }, "SM ATLAS · " + label + " · " + level));
  root.append(svg("text", {
    x:x+width*0.018,y:y+height+footHeight*0.73,
    fill:"#b7c9d4","font-family":"sans-serif",
    "font-size":font*0.9,
  }, "SAVED CENTERLINES AND PLACEMENT BOUNDS ONLY · NOT VERIFIED ROUTES OR ENTRANCES"));
  return new XMLSerializer().serializeToString(root);
}
