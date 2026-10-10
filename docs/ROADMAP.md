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
| User-facing browser explorer | **Not implemented** in the present repository |

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

- [ ] Introduce a minimal TypeScript browser application with local file selection.
- [ ] Read and validate a `save.db` locally (SQLite/WASM and background processing as needed); never upload the original file.
- [ ] Display discovered underground worlds/depths and **save-supported** connections, entrances or tunnel layout in an interactive view.
- [ ] Distinguish **saved-data facts**, **candidate geometry** and **unknown collision** in the interface.
- [ ] Exercise the prototype against an authentic Scrap Mechanic 1.0 test save and document unsupported cases.

**Acceptance criterion:** a player can open a local save and navigate at least one useful underground topology view without installing or running the Python CLI. No validated collision route is implied where none exists.

### P2 — Reliable underground mapping

- [ ] Reconstruct enough underground geometry for useful mine-level maps, with provenance and uncertainty.
- [ ] Identify entrances, elevators, level transitions, underground structures and POIs where evidence permits.
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

## Next action

**Developer:** start the local-first browser proof of concept around underground world discovery and known saved-data links. Continue geometry validation in parallel when test-game observations become available.

**Player:** no action required now. When a fresh physics probe is needed, provide exact, reversible game-side instructions and use the disposable test save.
