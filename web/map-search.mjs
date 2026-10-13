/**
 * Saved-object search for the selected underground world.
 * Labels are exact game-asset filenames when present in the UUID catalog;
 * never infer a resource deposit or route from unspecified collision data.
 */
const RESOURCE_TAGS = new Set([
  "deposit", "gold", "sapphire", "sparkstone", "potato", "crystal", "corralium",
]);
const SEARCH_FILTERS = new Set([
  "all", "cave", "elevator", "passage", "deposit", "resource", "unknown",
]);

// Categories describe saved catalog names/tags, never observed ore or passable space.
function savedObjectFacets(asset, kind) {
  const categories = kind === "group" ? ["cave"] : [];
  if (!asset) return [...categories, "unknown"];
  const tags = new Set(asset.tags || []);
  if (asset.family === "elevator" || tags.has("elevator")) categories.push("elevator");
  if (tags.has("passage")) categories.push("passage");
  if (tags.has("deposit")) categories.push("deposit");
  if ([...tags].some((tag) => RESOURCE_TAGS.has(tag))) categories.push("resource");
  return categories;
}

export function indexSavedObjects(result) {
  if (!result || result.status !== "available") return [];
  const output = [];
  for (const group of result.caveGroups || []) {
    output.push({
      kind: "group", id: group.id, index: null,
      facets: savedObjectFacets(group.asset, "group"),
      label: group.asset?.name || "Unidentified cave group G" + group.id,
      details: "Cave group G" + group.id + " · " + group.fragmentCount + " cells"
        + (group.sourceAware
          ? (group.sourceComplete && group.sizeMatches
            ? " · source placement consistent" : " · source placement incomplete/ambiguous")
          : " · adjacency-only candidate"),
      searchText: [group.asset?.name, group.asset?.family,
        ...(group.asset?.tags || []), group.tileUuid,
        "cave group", "G" + group.id].filter(Boolean).join(" ").toLowerCase(),
      x: group.x + group.width / 2,
      y: group.y + group.depth / 2,
    });
  }
  const groupedFragments = new Set();
  for (const group of result.pocketGroups || []) {
    for (const index of group.fragments) groupedFragments.add(index);
    output.push({
      kind: "pocket-group", id: group.id, index: group.fragments[0],
      facets: savedObjectFacets(group.asset, "pocket-group"),
      label: group.asset.name,
      details: "Logical pocket placement PG" + group.id + " · "
        + group.fragmentCount + " saved fragments"
        + (group.complete ? " · source coverage matches" : " · partial/ambiguous"),
      searchText: [group.asset.name, group.asset.family,
        ...(group.asset.tags || []), group.tileUuid,
        "pocket group", "PG" + group.id].filter(Boolean).join(" ").toLowerCase(),
      x: group.x + group.width / 2,
      y: group.y + group.depth / 2,
    });
  }
  for (const [index, piece] of (result.footprints || []).entries()) {
    if (piece.kind !== "pocket" || groupedFragments.has(index)) continue;
    output.push({
      kind: "pocket", id: null, index,
      facets: savedObjectFacets(piece.asset, "pocket"),
      label: piece.asset?.name || "Unidentified pocket tile #" + piece.tileIndex,
      details: "Pocket placement · XY " + piece.x + ", " + piece.y,
      searchText: [piece.asset?.name, piece.asset?.family,
        ...(piece.asset?.tags || []), piece.tileUuid,
        "pocket", "tile " + piece.tileIndex].filter(Boolean).join(" ").toLowerCase(),
      x: piece.x + piece.width / 2,
      y: piece.y + piece.depth / 2,
    });
  }
  return output;
}

export function searchSavedObjects(items, query, limit = 30, filter = "all") {
  const terms = String(query || "").trim().toLowerCase().slice(0, 100)
    .split(/\s+/).filter(Boolean);
  if (!SEARCH_FILTERS.has(filter) || (!terms.length && filter === "all")) {
    return { matches: [], total: 0 };
  }
  const matches = [];
  let total = 0;
  const bound = Number.isInteger(limit) && limit >= 0 ? Math.min(limit, 100) : 30;
  for (const item of items) {
    if (filter !== "all" && !item.facets?.includes(filter)) continue;
    if (!terms.every((term) => item.searchText.includes(term))) continue;
    total++;
    if (matches.length < bound) matches.push(item);
  }
  return { matches, total };
}


/** Preserve discoverability on all worlds when one level dominates matches. */
export function searchSavedObjectsAcrossWorlds(items, query, limit = 30, filter = "all") {
  const byWorld = new Map();
  for (const item of items) {
    if (!byWorld.has(item.worldId)) byWorld.set(item.worldId, []);
    byWorld.get(item.worldId).push(item);
  }
  const groups = [...byWorld.values()].map((entries) =>
    searchSavedObjects(entries, query, limit, filter));
  const bound = Number.isInteger(limit) && limit >= 0 ? Math.min(limit, 100) : 30;
  const matches = [];
  // Round-robin the visible results; total still counts ALL matches.
  for (let i = 0; matches.length < bound; i++) {
    let added = false;
    for (const group of groups) {
      if (matches.length >= bound) break;
      if (i < group.matches.length) {
        matches.push(group.matches[i]);
        added = true;
      }
    }
    if (!added) break;
  }
  return { matches, total: groups.reduce((sum, g) => sum + g.total, 0) };
}
