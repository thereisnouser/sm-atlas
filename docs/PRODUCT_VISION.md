# SM Atlas — Product Vision & Roadmap

## Product vision
SM Atlas is a browser-first, read-only Scrap Mechanic Survival save explorer.

Core idea:
- Drop a local `save.db` into the browser.
- Process it locally; the save does not need to leave the user's device.
- Visualize the entire Survival world, not only mines.
- Make difficult-to-discover world/save information easy to search, navigate and understand.

Working product name: **SM Atlas / Scrap Mechanic Atlas**

## Product principles
1. **Read-only first** — never modify the original save.
2. **Local-first privacy** — process saves in the browser whenever possible.
3. **Useful before pretty** — every milestone should solve a real player pain.
4. **Progressive depth** — surface map first, deeper save analysis and underground reconstruction step by step.
5. **Community tool, not a cheat menu** — focus on exploration, mapping, diagnostics and understanding the save.
6. **Web-first** — GitHub for source code; Cloudflare Pages is the current preferred hosting direction.
7. **No unnecessary backend** — use WASM, Web Workers and local storage unless a future feature truly needs a server.

## Main product areas

### 1. Overworld map
- Reconstruct surface terrain/cells from the save.
- POIs.
- Roads/biomes where data allows.
- Search and filters.
- Clickable cells with detailed metadata.

### 2. Underground / Mines
- Detect underground worlds.
- Separate levels/depths.
- Map entrances/elevators.
- Reconstruct tunnel geometry.
- Detect underground structures / POIs / loot where possible.
- Search a structure/item and jump directly to its map position.

This is the initial **killer feature**.

### 3. Other worlds / instances
- Warehouses.
- Dungeons / Growlab / other instanced worlds where identifiable.
- Visualize relationships between worlds.

### 4. Creations & vehicles
- Show player creations and vehicles on the map.
- Position and technical metadata.
- User-defined names/bookmarks.

### 5. World search
Global search for:
- POIs
- structures
- elevators
- vehicles
- resources
- loot/object UUIDs
- user markers

### 6. Map layers
Potential layers:
- Terrain
- Roads
- POIs
- Creations
- Vehicles
- Resources
- Units
- Loot
- Tunnels
- Entrances
- User markers

### 7. Personal markers
- Add markers and notes.
- Store locally in the browser.
- Later: optional export/import or sync.

### 8. Statistics / analysis
Examples:
- Explored area.
- Biome breakdown.
- Number of POIs.
- Number of creations.
- Underground levels detected.
- World/object counts.
- Useful save diagnostics.

### 9. Navigation helpers
- Distance between points.
- Direction / bearing.
- Draw straight-line route.
- Later investigate road/path-based navigation if enough map data exists.

### 10. Save Explorer
Advanced technical mode:
- Worlds.
- GenericData.
- ScriptData.
- RigidBody.
- ChildShape.
- Harvestable.
- Unit.
- Other useful database tables / decoded structures.

## Out of scope initially
Do NOT turn the early product into a save editor.

No initial features like:
- giving items,
- teleporting the player,
- deleting/moving game entities,
- editing inventory,
- modifying world state.

Possible future separate advanced tool, but not part of the core Atlas roadmap.

## Version roadmap

### v0.1 — Save loader
- Browser UI.
- Select / drag-and-drop `save.db`.
- SQLite WASM.
- Basic validation.
- Basic save/world info.
- Local-only processing.

### v0.2 — World discovery
- Decode GenericData.
- List all discovered worlds.
- Identify Overworld / Underground / other instance types where possible.
- Show world IDs, parameters, seeds/depth metadata.

### v0.3 — Overworld map
- Decode surface cell/tile information.
- Render interactive pan/zoom map.
- Basic terrain / tiles / rotation.
- Cell inspector.

### v0.4 — POIs & search
- Identify known POIs.
- Global search.
- Toggleable map layers.
- Jump-to-result.

### v0.5 — Creations / vehicles / objects
- Map creations and relevant save entities.
- Object details.
- Filtering.

### v0.6 — Underground viewer
- Discover and select underground depths/worlds.
- Map known underground entities / entrances / elevators.
- Diagnostic underground view.

### v0.7 — Tunnel reconstruction
- Reverse engineer / reproduce Scrap Mechanic 1.0 underground tunnel generation.
- Render true tunnel geometry.

### v0.8 — Underground POI & loot recognition
- Classify cave structures.
- Detect useful underground landmarks.
- Search and highlight underground points of interest / loot where reliably possible.

### v0.9 — UX / markers / world links
- Persistent markers.
- Better filters.
- Links between Overworld ↔ Underground / instance worlds.
- Export/import user data.
- PWA/offline polish.

### v1.0 — Public-quality release
- Stable browser-only experience.
- Strong UX.
- Full Overworld explorer.
- Useful Underground mapping.
- Search.
- Layers.
- Markers.
- Save Explorer.
- Documentation.
- Privacy explanation.
- Robust error handling for unsupported/corrupted saves.

## Longer-term possibilities
- Compare save snapshots.
- Show changes between sessions.
- Save history.
- Route planner.
- Shareable map exports that do not expose the original save.
- Optional cloud sync.
- Community-maintained UUID/POI database.
- Plugin/mod support.
- Desktop/PWA wrapper if browser limitations ever justify it.
- Localization.

## Monetization hypotheses
Build a genuinely useful community tool first.

Possible later monetization:
- Donations / Ko-fi / GitHub Sponsors.
- Optional supporter tier.
- Optional Pro features that do not cripple the core mapper:
  - multi-save history,
  - save comparisons,
  - advanced analytics,
  - cloud-sync for markers,
  - advanced exports,
  - heavy route/planning tools.
- Sponsorships if the project gains a meaningful audience.
- Open-source core + paid convenience features is a possible model.

Do not lock the essential pain-solving map behind an aggressive paywall before the project proves demand.

## Current technical direction
- Frontend: TypeScript/JavaScript.
- Browser SQLite via WASM.
- LZ4 / Lua-pickle decoding in browser.
- Web Workers for heavy parsing.
- Canvas/WebGL/SVG depending on map performance needs.
- PWA/local storage.
- GitHub as source repository.
- Cloudflare Pages as preferred hosting.
- No backend initially.

## Immediate next milestone
Build the first real web prototype:
1. Create repository.
2. Deploy a minimal site.
3. Implement local `save.db` loading.
4. Read SQLite schema safely.
5. Display basic save info.
6. Begin world discovery.
7. Test against a real Scrap Mechanic 1.0 save.

## Product thesis
The project is worthwhile because it removes an existing player pain:
Scrap Mechanic contains useful world information that is difficult or impossible to inspect conveniently in-game. SM Atlas turns that opaque save data into an understandable, searchable, interactive map.

The underground mapper is the differentiating feature; the complete save/world explorer is the larger product.
