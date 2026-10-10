# SM Atlas — Active Roadmap

_Last reviewed: 2026-10-10. Update this file whenever the active milestone or the evidence changes._

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
| User-facing browser explorer | Local browser previews saved tunnel lines, cave/pocket groups, asset labels, and evidence-based coverage badges per underground world; full authentic-save browser parity remains pending |

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
- [ ] Complete authentic-save parity validation in an actual browser. Read-only offline schema/LUA inspection of an authentic test save has confirmed an important sparse-world scenario (some underground worlds lack saved tunnel/placement records); synthetic SQLite WASM checks remain separate evidence. Never commit the private save.

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

## Next action

**Developer:** complete an in-browser smoke test on an authentic test save and compare its aggregate world/portal/underground geometry counts against independent offline results, without publishing the save. Then evaluate portal/entry position alignment with saved asset footprints. Keep collision and player clearance unverified pending in-game evidence; do not expand README with experiments. Continue geometry validation in parallel when test-game observations become available.

**Player:** no action required now. When a fresh physics probe is needed, provide exact, reversible game-side instructions and use the disposable test save.
