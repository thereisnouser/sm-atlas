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
| User-facing browser explorer | Browser previews caves, saved tunnels, asset labels and portal cells. Distinct portal rows sharing one cell are grouped in an inspectable marker with navigation to linked worlds, avoiding overlapping controls. Local synthetic Chromium/JS/Python acceptance passes; full authentic-save Chromium parity remains pending. |

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
- [ ] Run Chromium acceptance and exact module-coordinate parity against the **authentic private save**. The previous independent reconstruction matched geometry counts, but the committed full browser check still has to pass with the real file; never publish it.

**Acceptance criterion:** a player can open a local save and navigate at least one useful underground topology view without installing or running the Python CLI. No validated collision route is implied where none exists. **Not yet accepted:** authentic-save integration and a hosted build remain pending. The static build now packages the pinned SQLite WASM runtime on the same origin and processes saves in a worker; offline/PWA behavior and authentic-save integration remain unverified.

### P2 — Reliable underground mapping

- [ ] Reconstruct enough underground geometry for useful mine-level maps, with provenance and uncertainty. The browser now groups face-adjacent cave cells by saved tile identity, rotation and Z into inspectable **logical placement groups**. Actual room names, interior shapes, entrances and player clearance remain unverified.
- [ ] Identify entrances, elevators, level transitions, underground structures and POIs where evidence permits. **Asset-name recognition now works for known tile UUIDs**, including catalog elevator and passage tags; these are file-name hints, not verified navigable entrance coordinates.
- [ ] Enable search and cross-world navigation.
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

**Developer:** run existing Chromium acceptance and coordinate-digest Python/JS parity against the authentic private save without publishing it, then investigate precise portal door transforms. Keep the shared-cell marker as a coordinate region, never an inferred walkable entrance; keep README concise.

**Player:** no action required now. When a fresh physics probe is needed, provide exact, reversible game-side instructions and use the disposable test save.
