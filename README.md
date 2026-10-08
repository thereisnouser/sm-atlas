# SM Atlas

Interactive world and save explorer for **Scrap Mechanic**.

Reads Survival save files locally and never modifies the original save.

## Status

**v0.1 — Save inspection**

- find local Survival saves;
- discover worlds and portal connections;
- decode confident voxel chunk coordinates;
- render voxel chunk occupancy maps;
- inspect table schemas and sample rows.

## Stack

Python 3.12+ · SQLite · pytest

## Run

```bash
pip install -e ".[dev]"
sm-atlas saves
sm-atlas worlds path/to/save.db
sm-atlas graph path/to/save.db
sm-atlas terrain path/to/save.db
sm-atlas terrain-map path/to/save.db --world 23 --output d6.svg
pytest
```

## Experimental underground voxel navigation

These tools inspect a game's original `.tile` file. They do not modify saves.

```bash
sm-atlas tile-voxel-space path/to/passage_2x3x2.tile
sm-atlas tile-voxel-walk path/to/passage_2x3x2.tile --from-socket cell0:node7 --to-socket cell0:node6
sm-atlas tile-voxel-walk path/to/passage_2x3x2.tile --max-step 0
sm-atlas tile-voxel-walk path/to/passage_2x3x2.tile --from-socket cell0:node7 --to-socket cell0:node6 --json
```

To inspect the per-step terrain evidence and placement inventory:

```bash
sm-atlas tile-voxel-walk path/to/passage_2x3x2.tile --from-socket cell0:node7 --to-socket cell0:node6 --elevation-details
sm-atlas tile-object-probe path/to/passage_2x3x2.tile --examples 20
sm-atlas tile-object-probe path/to/passage_2x3x2.tile --from-socket cell0:node7 --to-socket cell0:node6 --radius 5
sm-atlas tile-object-probe path/to/passage_2x3x2.tile --json
```

The walker reports low-nibble voxel density beneath both feet at every
candidate rise/drop. Intermediate values (8..14) suggest a boundary rather
than a fully dense voxel, **not proof of a physically traversable slope**.
The object probe currently recognizes fixed 69-byte `unknown` and 65-byte
`harvestable` records found in Drill2 tile version 15, and reports raw UUID,
position, rotation and scale. Other record layouts fail closed. Object UUID
and transforms do not supply the base mesh or collision definition. Optional `--from-socket` / `--to-socket` adds a distance-to-candidate-route list: distances refer only to placement origins, not object extents, collisions or navigability.

The `tile-voxel-space` command identifies connected *candidate empty space* using the low four voxel bits as a density hypothesis. The `tile-voxel-walk` command adds candidate standing cells (solid support below, two clear cells above by default), and graph edges along cardinal directions with an optional elevation change of up to one voxel. Elevation-change edges additionally require headroom on the lower side for the rise, in both travel directions. Output reports the number of flat, uphill, and downhill edges and separately shows the unverified distance from each socket to its closest candidate floor.

The walker also includes an **experimental inward socket terrain profile**: the raw voxel values sampled horizontally from each socket toward the tile interior, the first candidate-open cell, and a straight-line test from that cell to the chosen large-component floor. The centreline test does not include character radius/height or alternative routes. A blocked centreline indicates an obstruction in the density-based model, not a verified game collision. These fields are visible in text output and `--json`.

When a requested route ends in different candidate floor components, the walker now reports rejected neighbouring edges: elevation changes greater than `--max-step` or blocked lower-side headroom. Sockets also show a warning if the closest standing cell belongs to a different/smaller component than the closest eligible large floor. This makes it possible to investigate a disconnected socket without assuming it is a genuinely blocked doorway.

For example, investigate the passage's secondary floor network:

```bash
sm-atlas tile-voxel-walk path/to/passage_2x3x2.tile --from-socket cell0:node7 --to-socket cell0:node2
sm-atlas tile-voxel-walk path/to/passage_2x3x2.tile --from-socket cell0:node2 --to-socket cell0:node5
```

**Neither command establishes actual player walkability.** Both depend on an unverified density interpretation; the walk command does not yet account for game collision of placed assets, ramps, ladders, actual slope, or attachment distances between sockets and the nearest standing voxel. Results are diagnostics only and are not injected into normal Underground navigation.

SM Atlas is an unofficial community project and is not affiliated with Axolot Games.
