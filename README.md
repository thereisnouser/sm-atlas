# SM Atlas

**A local-first world explorer for Scrap Mechanic Survival.**

SM Atlas aims to turn a Survival `save.db` into an interactive, searchable browser map of the **whole world**: underground mines, entrances, tunnels, surface terrain, POIs, vehicles, creations and save metadata. The underground explorer is our first differentiating feature; the all-in-one save explorer is the final product.

**Planned player experience:** open a website, choose a local save, explore it without uploading data or installing multiple utilities. The preferred direction is browser-side SQLite/WASM, Web Workers and static hosting without an unnecessary backend.

## Current state

This repository currently contains a **Python research and inspection CLI**, not a finished browser application. It can inspect local saves, saved worlds and portal connections, and investigate underground tiles and candidate routes.

Real game raycasts have verified a small cave-ground patch, but **the exact voxel collision decoder, player walkability and reliable cave-floor routing are not established**. Experimental voxel outputs must not be presented as confirmed routes.

## Browser prototype

An early [browser world viewer](web/) now reads local `save.db` files with SQLite WASM and displays discovered worlds and saved portal relationships. It is a **research preview**, not a complete cave map or a hosted public release.

To build the static browser preview (Node.js 22+), run `cd web && npm ci && npm run build`, then start `python -m http.server 8000 --directory dist` from the `web` directory and open `http://localhost:8000`. A built preview can be served as static files with no backend, CDN dependency or save uploads. Save parsing takes place inside a Web Worker. Authentic-game-save and offline/PWA testing are still pending.

## Research CLI

Requires Python 3.12+.

```bash
python -m pip install -e ".[dev]"
sm-atlas --help
sm-atlas saves
sm-atlas worlds path/to/save.db
sm-atlas graph path/to/save.db
python -m pytest -q
```

Original Survival saves are read-only. Some optional **explicitly requested** in-game probes temporarily edit installed game scripts; see the safety and rollback procedure in the research documentation before using them.

## Project documents

- [Product vision and original version roadmap](docs/PRODUCT_VISION.md) — long-term product scope and principles.
- [Active roadmap and decisions](docs/ROADMAP.md) — current status, next milestone, acceptance criteria and priorities.
- [Underground ground-truth research](docs/VOXEL_GROUND_TRUTH.md) — experimental evidence, protocols and limitations.

SM Atlas is an unofficial community project and is not affiliated with Axolot Games.
