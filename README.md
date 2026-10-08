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

The walker reports candidate voxel density beneath both feet at every
candidate rise/drop. Partial density below the selected packing's maximum
(15 for 4 bits, 31 for 5 bits) suggests a surface boundary, **not proof
of a physically traversable slope**.

For routes with a candidate floor path, Atlas also reports an **experimental
fractional-height surface profile**. It linearly interpolates the
chosen density iso-level between the filled support voxel below a
standing position and the free voxel above it. It shows approximate
per-segment gradients and an estimated length derived from these
fractional heights. The threshold and voxel-center positions are
hypotheses; the result is **not the game's terrain mesh, player collision
surface, or a routing permission**. The `--elevation-details` flag prints
segments where the estimated grade exceeds 0.5. JSON includes all
surface-height samples and segment gradients. Route search still uses
the original discrete floor graph and retains the existing default
`--density-bits 4` for reproducibility.

**Surface-gradient sensitivity (opt-in):** `--max-surface-gradient 1.0`
runs a second floor-path search that discards candidate edges exceeding
that experimental vertical isoheight change per horizontal metre. The
original unconstrained path is still reported unchanged. The additional
diagnostic also finds the *minimum possible bottleneck grade* between
the same fixed candidate floor endpoints and lists the critical edge(s).
A missing constrained path does not imply the real terrain is unwalkable;
this is a test of an unverified density interpretation and a 1 m grid,
not verified game character slopes or collision geometry.

```bash
sm-atlas tile-voxel-walk path/to/passage_2x3x2.tile --from-socket cell0:node7 --to-socket cell0:node6 --density-bits 5 --max-surface-gradient 1.0
```

On the Drill2 passage, the current estimated path has a maximum sampled
grade around 1.256; a minimax search can reduce the bottleneck to
approximately 1.233, but not to 1.0 without changing its candidate
start/end floors or the terrain model.
The object probe currently recognizes fixed 69-byte `unknown` and 65-byte
`harvestable` records found in Drill2 tile version 15, and reports raw UUID,
position, rotation and scale. Other record layouts fail closed. Object UUID
and transforms do not supply the base mesh or collision definition. Optional `--from-socket` / `--to-socket` adds a distance-to-candidate-route list: distances refer only to placement origins, not object extents, collisions or navigability.

The `tile-voxel-space` command identifies connected *candidate empty space*
under a **selectable, unverified byte-packing hypothesis**.
Both `tile-voxel-space` and `tile-voxel-walk` accept
`--density-bits 4` (legacy interpretation, mask `0x0f`, default cutoff `8`)
or `--density-bits 5` (alternate interpretation, mask `0x1f`, default cutoff `16`).
The **default remains 4 bits** to preserve earlier diagnostic outputs;
it is not an endorsement of that model. `--density-threshold` can override
the derived midpoint and is in raw masked density units, **not** normalized
physics density. The byte's upper bits are only *candidate* material IDs.

On the Drill2 `passage_08_2x3x2.tile`, the 4-bit model produces 142 candidate
floor components and an apparently disconnected passage. The 5-bit model
produces 46 components and a significantly smoother floor trajectory.
**This suggests the 5-bit hypothesis may be better**; it is not yet
verified by the game engine or an authoritative description of this old
tile's byte encoding. Do not apply different 4/5-bit route results as
ground truth. The separate modded runtime voxel format described at
scrapmechanictools.com is not evidence that an old tile uses the same packing.

To investigate an entrance with no large floor inside the default 5 m
socket radius, use `--socket-radius 6` (or another measured distance).
The CLI now independently reports (a) the closest low-density voxel within
2.5 m in *any direction* and (b) a candidate major floor inside a separate
10 m diagnostic search if it was missed by the requested socket radius.
These are proximity findings, **never confirmation of a traversable
entrance-to-floor connection**. The inward ray is only one sample line; it can
miss nearby open cells to the side.

If a route is requested with `--from-socket` and `--to-socket`,
`tile-voxel-walk` additionally probes each endpoint by a bounded shortest
**six-connected candidate-air path** from the nearest low-density voxel
(inside 2.5 m) to the selected candidate floor. The output counts positions
that do *not* satisfy the standing-support/headroom test. An air bridge
does **not** establish walkability, even if the selected floor-to-floor
route itself exists. The full air waypoints are available via `--json`.

The original Drill2 passage's `cell0:node4` socket is a useful example:
with `--density-bits 5 --socket-radius 6`, a 12-step air-only bridge can
be reconstructed between its nearby free voxel and a major floor anchor,
but **10 of the 13 sampled positions lack candidate standing support**.
This explicitly leaves `node4` entrance attachment unresolved.

For a controlled comparison:

```bash
sm-atlas tile-voxel-space path/to/passage_2x3x2.tile --density-bits 4
sm-atlas tile-voxel-space path/to/passage_2x3x2.tile --density-bits 5
sm-atlas tile-voxel-walk path/to/passage_2x3x2.tile --from-socket cell0:node7 --to-socket cell0:node6 --density-bits 4
sm-atlas tile-voxel-walk path/to/passage_2x3x2.tile --from-socket cell0:node7 --to-socket cell0:node6 --density-bits 5
sm-atlas tile-voxel-walk path/to/passage_2x3x2.tile --from-socket cell0:node4 --to-socket cell0:node6 --density-bits 5 --socket-radius 6
sm-atlas tile-object-probe path/to/passage_2x3x2.tile --from-socket cell0:node7 --to-socket cell0:node6 --density-bits 5 --examples 0
```
 The `tile-voxel-walk` command adds candidate standing cells (solid support below, two clear cells above by default), and graph edges along cardinal directions with an optional elevation change of up to one voxel. Elevation-change edges additionally require headroom on the lower side for the rise, in both travel directions. Output reports the number of flat, uphill, and downhill edges and separately shows the unverified distance from each socket to its closest candidate floor.

The walker also includes an **experimental inward socket terrain profile**: the raw voxel values sampled horizontally from each socket toward the tile interior, the first candidate-open cell, and a straight-line test from that cell to the chosen large-component floor. The centreline test does not include character radius/height or alternative routes. A blocked centreline indicates an obstruction in the density-based model, not a verified game collision. These fields are visible in text output and `--json`.

When a requested route ends in different candidate floor components, the walker now reports rejected neighbouring edges: elevation changes greater than `--max-step` or blocked lower-side headroom. Sockets also show a warning if the closest standing cell belongs to a different/smaller component than the closest eligible large floor. This makes it possible to investigate a disconnected socket without assuming it is a genuinely blocked doorway.

For example, investigate the passage's secondary floor network:

```bash
sm-atlas tile-voxel-walk path/to/passage_2x3x2.tile --from-socket cell0:node7 --to-socket cell0:node2
sm-atlas tile-voxel-walk path/to/passage_2x3x2.tile --from-socket cell0:node2 --to-socket cell0:node5
```

## Underground tile-local to saved-world coordinates

When a saved tile has a known layout node ID, inspect its actual saved
placement and match its socket positions to independent saved tunnel
endpoints without guessing the world origin:

```powershell
sm-atlas tile-world-probe $save $tile --world 23 --node 322 --edge "4,35,19" "3,35,20"
sm-atlas tile-world-probe $save $tile --world 23 --node 322 --edge "4,35,19" "3,35,20" --json > world-ground-probe.json
```

The command fails on a tile UUID or dimensions mismatch. It reports world
coordinates for all local sockets, independent saved tunnel anchor matches,
and up to 15 proposed XY raycast sampling locations for a cardinal edge.
It needs the same actual saved world that contains the selected tile
instance: `--node 322` is a layout node ID, **not a tile-local socket**.
See [ground-truth validation protocol](docs/VOXEL_GROUND_TRUTH.md).
**Saved transform agreement is not actual in-game terrain collision validation.**

### Optional in-game surface measurement

With a `tile-world-probe` JSON plan whose socket alignment is supported by
at least two independent saved tunnels, Atlas can generate a *callable but
not installed* Scrap Mechanic Lua function, and compare game log observations:

```powershell
sm-atlas tile-world-probe $save $tile --world 23 --node 322 --edge "4,35,19" "3,35,20" --json --output ground_plan.json
sm-atlas tile-ground-lua ground_plan.json --output atlas_ground_probe.lua
# Integrate the generated function into your OWN game script, with a real
# World userdata. Capture ATLAS_GROUND lines from the running game's log.
sm-atlas tile-ground-compare ground_plan.json atlas_ground_hits.log
```

No mod is installed and no game code is edited by these commands.
The comparison detects missed rays and terrain assets separately, records
actual hit heights and surface normals, and estimates observed gradients.
**No game-physics measurements have yet been taken for this tile.**
See [ground-truth protocol](docs/VOXEL_GROUND_TRUTH.md) for callback
integration and interpreting the results.

For validating these candidate surfaces against the actual in-game physics
terrain, see [Voxel ground-truth protocol](docs/VOXEL_GROUND_TRUTH.md).
The protocol uses the official game raycast API and explicitly requires a
verified tile-local to underground-world transform; it has not yet been run.

**Neither command establishes actual player walkability.** Both depend on an unverified density interpretation; the walk command does not yet account for game collision of placed assets, ramps, ladders, actual slope, or attachment distances between sockets and the nearest standing voxel. Results are diagnostics only and are not injected into normal Underground navigation.

SM Atlas is an unofficial community project and is not affiliated with Axolot Games.
