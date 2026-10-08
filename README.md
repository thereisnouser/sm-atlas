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

The `tile-voxel-space` command identifies connected *candidate empty space* using the low four voxel bits as a density hypothesis. The `tile-voxel-walk` command adds candidate standing cells (solid support below, two clear cells above by default), and graph edges along cardinal directions with an optional elevation change of up to one voxel. Elevation-change edges additionally require headroom on the lower side for the rise, in both travel directions. Output reports the number of flat, uphill, and downhill edges and separately shows the unverified distance from each socket to its closest candidate floor.

**Neither command establishes actual player walkability.** Both depend on an unverified density interpretation; the walk command does not yet account for game collision of placed assets, ramps, ladders, actual slope, or attachment distances between sockets and the nearest standing voxel. Results are diagnostics only and are not injected into normal Underground navigation.

SM Atlas is an unofficial community project and is not affiliated with Axolot Games.
