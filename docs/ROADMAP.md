# SM Atlas — Active Roadmap

_Last reviewed: 2026-10-12. Update this file whenever the active milestone or the evidence changes._

## Product north star

A **browser-first, local-first, read-only all-in-one Scrap Mechanic Survival explorer**. The player chooses a `save.db`, which stays on their device, and receives searchable maps and insights for the **entire Survival world**. No unnecessary backend, separate downloadable tools or complex manual file preparation for the finished product.

**Underground/mines first** is the current execution priority and product differentiator, **not** a reduction of the overall scope. For the complete original v0.1–v1.0 vision, read [PRODUCT_VISION.md](PRODUCT_VISION.md). Its original version labels are goals, **not** claims that those releases already exist.

## Current reality

| Area | Verified state |
| --- | --- |
| Python save inspection | Existing local read-only CLI and tests |
| Saved world / portal / tunnel relationships | Research tooling exists; saved topology can be inspected |
| Cave physical ground evidence | 15 real Drill2 upward `voxelTerrain` hits from 2026-10-08 |
| Broader cave sampling | Separate 25-point off-grid plan prepared; **new game hits not yet verified here** |
| Voxel collision decoder and player-walkable routing | **Unverified**; competing candidate models disagree with actual terrain |
| User-facing browser explorer | The shipped JavaScript decoder and independent Python research agree on saved layout coordinates in an authentic private save (25 worlds, 69 portals, 8 underground worlds, 6,702 tunnel points). Saved asset search now spans all underground worlds with direct map navigation and reconstructed known-pocket placements, without uploading the save; synthetic Chromium tests cover selection, zoom and cross-world results. Authentic visual Chromium parity remains unverified. |

Experiments, raw-byte hypotheses and their reproducibility details belong in
[VOXEL_GROUND_TRUTH.md](VOXEL_GROUND_TRUTH.md), **not** the README or this execution plan.

## Active work — cave-first product development

### P0 — Independent cave geometry validation (research gate)

**Purpose:** avoid displaying fictional paths or unreachable areas.

- [x] Anchor the target underground tile to a saved world using independent tunnel matches.
- [x] Capture and compare initial real in-game cave-ground raycasts.
- [x] Preserve candidate-model uncertainty instead of declaring a decoder correct.
- [x] Prepare a spatially wider 25-ray experiment and safe full-log extraction.
- [ ] Obtain authentic off-grid game-physics observations for the new grid in a disposable test save.
- [ ] Compare candidate surfaces/normals against new observations, with spatial coverage and missing-hit accounting.
- [ ] Establish a validated terrain/collision model **before** permitting voxel-based player-route claims.

**Acceptance criterion:** evidence from new physical measurements can independently discriminate terrain hypotheses; unsupported areas remain marked unknown. A good in-sample fit alone is insufficient.

**Dependency on the player:** only the eventual game-side capture of the new rays. All other preparatory research and implementation remains developer-owned.

### P1 — First genuinely useful browser slice (next autonomous build)

**Purpose:** shift from a research-only command-line toolkit toward the promised player experience without waiting for a complete voxel decoder.

- [x] Introduce a minimal dependency-free JavaScript browser prototype with local file selection (TypeScript migration remains optional).
- [x] Add browser-side SQLite/WASM ingestion and binary record decoding; no save upload API. Use a background worker for CPU-heavy parsing and a static bundle with local WASM files. Confirm performance on authentic large saves before calling this production-ready.
- [x] Display decoded worlds/depths and **save-supported** Portal relationships. Overlay saved ScriptData tunnel centerlines and individually decoded cave/pocket placement rectangles in a top-down view; no actual collision interiors or entrances claimed.
- [x] Explicitly label world/portal saved facts and unknown walking/collision geometry; no candidate surfaces promoted to real routes.
- [x] Exercise the **built static site** in real Chromium against a synthetic local SQLite save: file picker, worker, pinned WASM, underground coverage, saved cave/tunnel SVG, switching worlds, no unexpected external requests.
- [x] Implement local-only Chromium acceptance that compares the rendered SVG geometry counts against independent Python extraction, with off-origin requests blocked; exercise it on generated data in CI.
- [x] Run the actual browser JavaScript decoders against the authentic private save; independently cross-check decoded terrain record IDs, **6,702 saved tunnel point coordinates** and every cave/pocket placement with separate Python execution and SHA-256 digests on all eight worlds. Exact numeric digests are private and were not committed.
- [ ] Complete the **authentic private-save Chromium visual acceptance** and execute the project's checked-in full parity wrapper on a browser-enabled machine. The independent coordinate-level decoder comparison has passed, but the hosted browser's visual state on that same private save remains unverified. Never publish the save.

**Acceptance criterion:** a player can open a local save and navigate at least one useful underground topology view without installing or running the Python CLI. No validated collision route is implied where none exists. **Not yet accepted:** authentic-save integration and a hosted build remain pending. The static build now packages the pinned SQLite WASM runtime on the same origin and processes saves in a worker; offline/PWA behavior and authentic-save integration remain unverified.

### P2 — Reliable underground mapping

- [ ] Reconstruct enough underground geometry for useful mine-level maps, with provenance and uncertainty. Known cave placements and pockets now use source-aware grouping for UUID-matched assets with valid offsets, avoiding merges of adjacent independent cave placements and duplicate results from split assets. Unidentified cave cells retain explicitly unverified adjacency-only groups. **Known pockets** also have source-aware logical placements (packed source offsets, rotation, tile dimensions and completeness checks), which avoids conflating adjacent instances and repeating one structure per fragment. Interior shapes, entrances and clearance remain unverified.
- [ ] Identify entrances, elevators, level transitions, underground structures and POIs where evidence permits. **Asset-name recognition now works for known tile UUIDs**, including catalog elevator and passage tags; these are file-name hints, not verified navigable entrance coordinates.
- [x] Search source-backed cave groups and pocket asset names/tags within the selected world or **across all underground worlds**, showing the destination world and focusing the chosen saved coordinates after navigation. Indexing is local-only in the existing Worker, uses compact results and batches 32 worlds. This is structural search, not pathfinding.
- [x] Browse saved underground structures without guessing a name: elevator, passage, deposit, resource-tagged, cave group or unidentified filters work in the selected world and across all worlds. Labels come from saved catalog metadata; no loot or traversability is inferred.
- [ ] Add actual traversable routing only after physics/clearance validation.

### P3 — Complete world explorer

Deliver the remainder of the [original product areas](PRODUCT_VISION.md): surface map, other instances, POIs, global search, vehicles/creations, layers, markers, statistics, navigation helpers and advanced save inspection. Progress toward the browser MVP should not abandon the cave research track.

### P4 — Public-ready delivery

Improve usability, performance, local privacy, error handling for corrupted/unsupported saves, documentation, offline/PWA experience and static deployment. Cloudflare Pages remains a **preferred direction**, not an existing deployment claim.

## Engineering and research standards

- **Truth over appearance:** game-physics measurements and saved-record facts are separate from inferred geometry; never silently promote hypotheses to ground truth.
- **Read-only and local-first:** protect original saves. Game-script hooks require explicit opt-in and a reversible, backed-up process.
- **Python/ML excellence where it helps:** keep decoders, geometric reasoning, reproducible experiments, ground-truth datasets, evaluation and failure analysis scientifically rigorous. Use ML for classification/prediction **only when labelled evidence, simple baselines and honest out-of-sample evaluation justify it**; no decorative or fabricated AI.
- **Repository hygiene:** all code, PRs, branches, commits and repository documentation in English. Keep README concise. Organize enduring findings in the research document; archive transient experiments in Git history rather than accumulating duplicate files. Keep tests meaningful and proportional to behavior. Prefer short-lived branches and prune merged branches when access permits.
- **Manager-facing communication:** explain what improved, why it matters to players, what remains unknown and what happens next. Technical internals and local commands only when needed for action.

## Decision log

| Date | Decision | Why |
| --- | --- | --- |
| 2026-10-10 | Preserve the original product vision separately from the active roadmap | Long-term scope should not be overwritten by research detours |
| 2026-10-10 | Prioritize caves while building a browser-first, all-in-one product | An underground map is the differentiator, not the only feature |
| 2026-10-10 | Start the browser slice from verified saved topology before voxel-collision routing | Provide player value without pretending an unverified surface model is real |
| 2026-10-10 | Keep README short and experimental evidence in dedicated documentation | Improve discoverability and avoid repository clutter |
| 2026-10-10 | Use measurable Python research; introduce ML only when justified by data | Demonstrate trustworthy engineering and model-evaluation expertise |
| 2026-10-10 | Launch browser exploration with saved world IDs and Portal table before full voxel geometry | Give players a functional cave-world overview without fabricating traversable terrain |
| 2026-10-10 | Self-host the SQLite runtime and move parsing off the UI thread | Avoid runtime CDN dependency and keep the interactive explorer responsive on demanding saves |
| 2026-10-10 | Render saved ScriptData tunnel centerlines before attempting voxel collision geometry | Deliver an honest spatial underground overview based on actual stored coordinates, not fabricated walkable paths |
| 2026-10-10 | Overlay cave and pocket allocation footprints as separate layers | Reveal authentic saved tile placements without pretending bounding boxes equal accessible interior space |
| 2026-10-10 | Group cave cells by matching saved tile identity, rotation, depth and shared face | Replace a wall of rectangles with inspectable logical placement groups without inventing room interiors or labels |
| 2026-10-10 | Match saved tile UUIDs to the existing licensed catalog of 193 known underground assets | Label real saved structure assets and check expected dimensions while retaining unknown identities and unverified interiors |
| 2026-10-10 | Prioritize underground worlds with saved layout data and explicitly mark sparse levels | Authentic offline save inspection showed legitimate underground world records with no saved tunnel/placement geometry; an empty map must not imply an empty cave |
| 2026-10-12 | Test the actual browser application in headless Chromium with a generated local save | Validate File API, static SQL/WASM loading, background worker, world selection and SVG output together without publishing private game data |
| 2026-10-12 | Show saved portal endpoint cells as a separate underground overlay | A private authentic test save places known portal endpoint cells on saved cave placements on D2/D4/D6. Mark the 64-unit grid region instead of inventing precise door positions. |
| 2026-10-13 | Aggregate co-located portal endpoints into inspectable cell markers | Authentic Mining Hub data has eight distinct Portal rows in the same cell (-2, 2); overlapping independent rectangles hid destinations. Keep every record and permit navigation without inventing door positions. |
| 2026-10-13 | Add bounded zoom/pan to underground map | The authentic save has 295 tunnel segments and 666 pocket placements on D4 and 286/687 on D6; precise inspection needs cursor-oriented zoom and drag without altering game coordinates. |
| 2026-10-13 | Verify real-save XY/Z geometry using independent execution and add in-level saved asset search | Python and actual JavaScript agree on terrain IDs, 6,702 float32 tunnel coordinates and all placement coordinate digests on eight worlds. D4/D6 contain hundreds of named resource and pocket objects; find-by-filename is more useful than browsing a flat crowded map. |
| 2026-10-13 | Search named saved placements across underground worlds using the local Worker | Cross-level discovery reuses decoded layout cache, transfers only index metadata, and navigates directly to the selected saved object without treating catalog names as verified walkable locations. |
| 2026-10-13 | Port Python source-aware logical pocket reconstruction to the browser | Packed pocket records contain source chunk offsets; grouping by UUID, source origin, rotation and height avoids treating split pieces as independent structures and checks saved source coverage without inferring traversable interiors. |
| 2026-10-13 | Reconstruct known cave placements by packed source-cell origins | Adjacent repeated same-UUID caves are different placements when their saved source origins differ; preserve unknown adjacency as uncertain and cross-check Python/browser counts. |
| 2026-10-13 | Add source-backed category browsing to underground search | Players can explore named assets by supported catalog tag even without a text query; preserve global balance and unknown identity. |
| 2026-10-13 | Validate source-aware browser pocket reconstruction on a private authentic save | With shipped browser JS and independent Python extraction: D4 has 666 saved fragments forming 549 logical known pockets (83 multi-fragment); D6 has 687 forming 545 (102 multi-fragment). Every reconstructed group has full source coverage and expected recorded bounds; these are placement consistency checks, not collision evidence. |

## Source-aware pocket instance verification (2026-10-13)

Downloaded the static browser artifact produced by GitHub Actions, ran the
shipped decoder and source-aware pocket grouping against the **private local**
71,270,400-byte Survival save, and compared per-world aggregate pocket placement
results with a separately executed Python implementation reading the raw
ScriptData/LUA fields.

| World | Saved pocket fragments | Source-backed logical placements | Multi-fragment placements | Complete |
| --- | ---: | ---: | ---: | ---: |
| D4 (Drill 1) | 666 | 549 | 83 | 549 |
| D6 (Drill 2) | 687 | 545 | 102 | 545 |

Both independent readers also found **zero overlapping source chunks and zero
catalog extent mismatches** across the known reconstructed placements. The
other six underground worlds contain no pocket fragments. These checks verify
saved placement relationships and catalog dimensions, **not** navigable space.
The real save and any private coordinates remain outside the repository.
The developer-only parity probe now compares the new group counts too.

## Independent exact coordinate parity (2026-10-13)

On the **private local** 71,270,400-byte save, a separately executed Python
decoder (SQLite read-only, raw ScriptData/LZ4/LUA decoding) was compared with
the **actual bundled browser JavaScript** running the same local pinned
SQLite WASM runtime. For each of the eight underground worlds, selected
ScriptData row IDs, counts, and SHA-256 digests of the ordered 3D tunnel
centerline coordinates and every saved cave/pocket rectangle agreed exactly.
D4 had 3,378 tunnel points and D6 had 3,324; other worlds had zero tunnel
points. No private geometry fingerprints or game save data were committed.

This is **not** the same as successfully navigating the authentic save in
Chromium. The local Chromium security policy blocks even localhost URLs.
The in-repository Chromium acceptance test still runs against synthetic
local saves in CI; authentic-save UI parity remains pending.

## Authentic-save browser module validation (2026-10-13)

The exact JavaScript decoder modules from the GitHub Actions static build were
run against the private 71,270,400-byte test save locally using the bundled
pinned `sql.js` WASM library. Results: 25 worlds, 69 portals, 8 underground
levels; D4: 295 tunnel lines, 26 cave cells, 666 pocket placements;
D6: 286 tunnel lines, 26 cave cells, 687 pocket placements. All eight
world terrain decoders completed without errors. This establishes real-save
**module decoding**, not a full Python coordinate-digest parity run.
Chromium navigation from this local environment was blocked by its browser
security policy even for localhost and file URLs, so real-save
**visual UI acceptance** is still unverified; CI continues to run
synthetic-browser smoke tests. No private save bytes were committed.

## Private-save Chromium acceptance (development only)

Build the static site, install the Python package and Playwright Chromium, then
run `python scripts/browser_acceptance.py --save "/private/path/to/save.db"`.
The checker serves the actual browser app on localhost, loads the original
file via the normal file picker, **blocks all non-local requests**, and compares
rendered world, portal, tunnel, cave and pocket counts with independently decoded
Python results. It creates no save copies, screenshots or private reports.
Its `--synthetic` mode is exercised in CI.

## Local authentic-save parity check (development only)

After installing Python development dependencies and running `npm ci` in `web/`,
run `python scripts/verify_browser_parity.py /path/to/save.db` from the repository root.
It compares the **existing Python decoders** against the **actual browser decoding
modules** using local SQLite WASM: world identities, saved portal counts, chosen
terrain records, geometry counts and SHA-256 digests of tunnel coordinates and
placement records. The original save stays read-only; no private test save or
generated report is committed. This command is not required for ordinary players.

## Next action

**Developer:** verify newly reconstructed cave source groups against the private authentic save, then complete authentic-save Chromium visual acceptance in a browser-enabled environment; independent Python/JS coordinate comparison is already confirmed. Investigate reliable physical entrance transforms and continue voxel collision research before routing. Keep structural global search factual, and README concise.

**Player:** no action required now. When a fresh physics probe is needed, provide exact, reversible game-side instructions and use the disposable test save.
