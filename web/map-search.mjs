/**
 * Saved-object search for the selected underground world.
 * Labels are exact game-asset filenames when present in the UUID catalog;
 * never infer a resource deposit or route from unspecified collision data.
 */
export function indexSavedObjects(result) {
  if (!result || result.status !== "available") return [];
  const output = [];
  for (const group of result.caveGroups || []) {
    output.push({
      kind: "group", id: group.id, index: null,
      label: group.asset?.name || "Unidentified cave group G" + group.id,
      details: "Cave group G" + group.id + " · " + group.fragmentCount + " cells",
      searchText: [group.asset?.name, group.asset?.family,
        ...(group.asset?.tags || []), group.tileUuid,
        "cave group", "G" + group.id].filter(Boolean).join(" ").toLowerCase(),
      x: group.x + group.width / 2,
      y: group.y + group.depth / 2,
    });
  }
  for (const [index, piece] of (result.footprints || []).entries()) {
    if (piece.kind !== "pocket") continue;
    output.push({
      kind: "pocket", id: null, index,
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

export function searchSavedObjects(items, query, limit = 30) {
  const terms = String(query || "").trim().toLowerCase().slice(0, 100)
    .split(/\s+/).filter(Boolean);
  if (!terms.length) return { matches: [], total: 0 };
  const matches = [];
  let total = 0;
  const bound = Number.isInteger(limit) && limit >= 0 ? Math.min(limit, 100) : 30;
  for (const item of items) {
    if (!terms.every((term) => item.searchText.includes(term))) continue;
    total++;
    if (matches.length < bound) matches.push(item);
  }
  return { matches, total };
}
