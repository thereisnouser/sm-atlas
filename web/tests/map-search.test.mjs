import test from "node:test";
import assert from "node:assert/strict";
import { indexSavedObjects, searchSavedObjects,
  searchSavedObjectsAcrossWorlds } from "../map-search.mjs";

function fixture() {
  return {
    status: "available",
    caveGroups: [
      {id: 1, x: 0, y: -64, width: 128, depth: 64, fragmentCount: 2,
        asset: {name: "onboarding_elevator_12x12x8.tile", family: "elevator",
          tags: ["elevator"]}, tileUuid: "11111111-1111-1111-1111-111111111111"},
      {id: 2, x: 192, y: 0, width: 64, depth: 64, fragmentCount: 1,
        asset: null, tileUuid: null},
    ],
    footprints: [
      {kind: "cave", x: 0, y: -64},
      {kind: "pocket", x: -32, y: 16, width: 32, depth: 32,
        tileIndex: 7, tileUuid: "22222222-2222-2222-2222-222222222222",
        asset: {name: "pocket_small_golddeposit1_2x2x1.tile",
          family: "pocket", tags: ["gold", "deposit"]}},
      {kind: "pocket", x: 64, y: 48, width: 16, depth: 16,
        tileIndex: 12, tileUuid: null, asset: null},
    ],
  };
}

test("search indexes known tile filenames and honest unknowns", () => {
  const entries = indexSavedObjects(fixture());
  assert.equal(entries.length, 4);
  assert.deepEqual(entries.map(e => e.kind), ["group", "group", "pocket", "pocket"]);
  assert.equal(entries[0].label, "onboarding_elevator_12x12x8.tile");
  assert.deepEqual([entries[0].x,entries[0].y], [64, -32]);
  assert.deepEqual([entries[2].x,entries[2].y], [-16, 32]);
  assert.equal(entries[2].index, 1); // original footprint offset, not pocket offset
  assert.equal(entries[3].label, "Unidentified pocket tile #12");
  assert.equal(entries[1].label, "Unidentified cave group G2");
});

test("multi-token search is case-insensitive, exact to saved catalog names", () => {
  const entries = indexSavedObjects(fixture());
  assert.equal(searchSavedObjects(entries, "GOLD DEPOSIT").total, 1);
  assert.equal(searchSavedObjects(entries, "gold deposit").matches[0].index, 1);
  assert.equal(searchSavedObjects(entries, "ELEVATOR").matches[0].id, 1);
  assert.equal(searchSavedObjects(entries, "unidentified").total, 0);
  assert.equal(searchSavedObjects(entries, "pocket tile 12").total, 1);
  assert.equal(searchSavedObjects(entries, "gold elevator").total, 0);
});

test("result limit affects display only, not real match count", () => {
  const base = indexSavedObjects(fixture());
  const matches = searchSavedObjects(base, "pocket", 1);
  assert.equal(matches.total, 2);
  assert.equal(matches.matches.length, 1);
  assert.deepEqual(searchSavedObjects(base, "", 10), {matches: [], total: 0});
  assert.deepEqual(searchSavedObjects(base, "  ", 10), {matches: [], total: 0});
  assert.deepEqual(indexSavedObjects({status: "unavailable"}), []);
});


test("global matches retain their world IDs and include later worlds when first is crowded", () => {
  const items = [
    ...Array.from({length: 75}, (_, i) => ({
      worldId: 21, searchText: "gold deposit", label: "gold on D4 #" + i,
    })),
    {worldId: 23, searchText: "gold deposit", label: "gold on D6"},
    {worldId: 22, searchText: "stone", label: "other material"},
  ];
  const result = searchSavedObjectsAcrossWorlds(items, "GOLD", 5);
  assert.equal(result.total, 76);
  assert.equal(result.matches.length, 5);
  assert.deepEqual(result.matches.map((o) => o.worldId), [21, 23, 21, 21, 21]);
  assert.equal(searchSavedObjectsAcrossWorlds(items, "unobtainium").total, 0);
  assert.deepEqual(searchSavedObjectsAcrossWorlds(items, "", 5),
    { matches: [], total: 0 });
});

test("global index selects objects by world and original placement index", () => {
  const entries = indexSavedObjects(fixture()).map((entry) => ({
    ...entry, worldId: 23,
  }));
  assert.equal(searchSavedObjectsAcrossWorlds(entries, "gold").matches[0].worldId, 23);
  assert.equal(searchSavedObjectsAcrossWorlds(entries, "gold").matches[0].index, 1);
});


test("known split pocket is searchable once as a logical placement, not twice", () => {
  const original=fixture();
  original.footprints.splice(2, 0, {...original.footprints[1],
    x: 0, y: 16, width: 32, depth: 32});
  original.pocketGroups=[{
    id: 4, fragments:[1,2], fragmentCount:2,
    asset: original.footprints[1].asset,
    tileUuid: original.footprints[1].tileUuid,
    x:-32,y:16,width:64,depth:32,
    complete:true,
  }];
  const entries=indexSavedObjects(original);
  assert.equal(searchSavedObjects(entries,"gold").total,1);
  const [gold]=searchSavedObjects(entries,"gold").matches;
  assert.equal(gold.kind,"pocket-group");
  assert.equal(gold.id,4);
  assert.equal(gold.index,1);
  assert.deepEqual([gold.x,gold.y],[0,32]);
  assert.match(gold.details,/2 saved fragments/);
  assert.equal(searchSavedObjects(entries,"unidentified pocket").total,1);
});
