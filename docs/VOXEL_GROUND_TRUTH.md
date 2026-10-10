# Verification against Scrap Mechanic's actual terrain collision

**Status (2026-10-08): real in-game raycast measurement completed.** All
15 probe rays recorded collision type `voxelTerrain` in underground world
23, with upward normals at the target XY positions. This challenges the
candidate five-bit-density interpolated surface heights. The 5-bit
interpretation and walking/capsule clearance remain unverified.

## Reference data (Drill2 passage)

For `cell0:node7 -> cell0:node6` the selected candidate-floor route is
64.456 m on the discrete grid and 62.648 m under vertical density
interpolation. For fixed endpoints, minimizing the highest estimated grade
produces a bottleneck of 1.233333 near tile-local
`(4,35,19) -> (3,35,20)`. This does not prove an impassable incline.

The preview in this conversation was produced by Marching Cubes on the
assumed 5-bit density field. It is not a game mesh or a collision model.

## Official in-game measurement API

The game-script API documents:

- `sm.physics.raycast(start, end, body?, mask?, world?, ignoreUuids?)`
- `sm.physics.filter.terrainSurface` (ground) versus `terrainAsset`
- `RaycastResult.pointWorld`, `RaycastResult.normalWorld` and `.type`
- Older published `sm.physics.types` lists `terrainSurface`, but the
  2026 in-game Drill2 result explicitly used `voxelTerrain`. The
  comparator accepts both as candidate *ground collision* types and
  still requires an upward normal; it excludes assets/unknown hits.
- `sm.physics.capsulecast` for later character-clearance experiments

Sources:
- https://scrapmechanic.com/api/namespace_Game_sm_physics.html
- https://scrapmechanic.com/api/userdata_Game_RaycastResult.html

The following **reference function** must run inside an authorized game
Lua script with a real World userdata. Atlas does not currently install
such a script and this code has not been runtime-tested.

```lua
local function atlasProbeGround(world, x, y, expectedWorldZ)
    -- Use a narrow range known to be inside the tunnel cavity.
    -- A ray from above the cave may hit the ceiling instead of the floor.
    local top = sm.vec3.new(x, y, expectedWorldZ + 1.0)
    local bottom = sm.vec3.new(x, y, expectedWorldZ - 2.0)
    local hit, result = sm.physics.raycast(
        top, bottom, nil, sm.physics.filter.terrainSurface, world
    )
    if not hit or (result.type ~= "terrainSurface"
        and result.type ~= "voxelTerrain") then
        return { hit = false, x = x, y = y }
    end
    local p, n = result.pointWorld, result.normalWorld
    return {
        hit = true, x = p.x, y = p.y, z = p.z,
        nx = n.x, ny = n.y, nz = n.z, type = result.type,
    }
end
```

## Saved-instance coordinate mapping

Atlas now has a diagnostic CLI command (no game modification):

```powershell
sm-atlas tile-world-probe $save $tile --world 23 --node 322 --edge "4,35,19" "3,35,20"
sm-atlas tile-world-probe $save $tile --world 23 --node 322 --edge "4,35,19" "3,35,20" --json > world-ground-probe.json
```

This resolves the **saved placement** of an exact tile UUID within an
underground layout node. The command validates the tile UUID, rotated
dimensions and bounds; then compares every transformed TUNNEL socket with
saved tunnel endpoints. At least two distinct socket/endpoints on two
independent tunnels are required for status
`two_or_more_independent_tunnel_anchors`. Otherwise it reports
`insufficient_independent_tunnel_anchors`; no match is fabricated.

For the Drill2 tile and world 23, the saved tunnel endpoints previously
observed for #42 and #269 indicate layout rotation 1 (90 degrees CCW),
tile bounds minimum `(32,-112,64)` and maximum `(80,-80,96)`. The
**candidate** local-to-world coordinate map is:

```text
world_x = 80 - tile_y
world_y = -112 + tile_x
world_z = 64 + tile_z
```

The **integer** voxel indices `(4,35,19) -> (3,35,20)` therefore
correspond to `(45,-108,83) -> (45,-109,84)`. The **candidate voxel
centre** XY sampling locations instead correspond to
`(44.5,-107.5) -> (44.5,-108.5)`. Keep these conventions distinct.

With `--edge`, Atlas prints 15 measurement locations (at 0.25 m XY
intervals on three parallel tracks), including tentative world Z values.
The XY transform is derived from the saved layout; the sub-voxel terrain
Z estimates rely on an **unverified** 5-bit packing and vertical sample
origin. None are live raycast measurements.

## Live in-game coordinate verification remains unresolved

The saved-instance transform gives **candidate world-space positions**.
Database world ID 23 is *not* a game-engine World userdata. Before using
the in-game raycast:

1. Determine this particular tile instance's origin and rotation in the
   correct underground world.
2. Validate both XY axes using at least two known, distinct socket positions,
   not just one translated point. Resolve height origin and handedness.
3. Establish a consistent voxel-centre convention; the tentative +0.5
   offset in Atlas may differ from the engine's sample positions.
4. Place short downcast ranges *inside* the tunnel cavity to avoid ceiling
   hits; record misses and unexpected hit types explicitly.

Sample tile-local XY across the critical pair at centres
`(4.5,35.5)` and `(3.5,35.5)`, every 0.25 m between them, and parallel
tracks offset laterally by +/-0.5 m. After the transform, store
corresponding world XY, hit Z, world-space normal XYZ, hit type and whether
the player could traverse the point without jumping.

Compare observed `abs(z2-z1) / horizontal_distance` and surface normals
with the predictions from our candidate iso-surface. Actual character
walkability additionally requires clearance and collision-radius testing:
a successful ground raycast is **not** walking proof.

## Generate and compare a real Lua raycast measurement

Once `tile-world-probe` reports at least **two independent tunnel
anchors**, save the complete JSON and generate a callable Lua diagnostic:

```powershell
sm-atlas tile-world-probe $save $tile --world 23 --node 322 --edge "4,35,19" "3,35,20" --json --output .\ground_plan.json
sm-atlas tile-ground-lua .\ground_plan.json --output .\atlas_ground_probe.lua
```

The generated `atlas_ground_probe.lua` is **not automatically loaded into
Scrap Mechanic**. It defines `smAtlasGroundProbe(world)`; integrate the
function into your own permitted client/server Game script and invoke it
only after entering the correct, loaded underground world. In a client
Game script, the documented `sm.localPlayer.getWorld()` gives actual World
userdata. This reference call must be placed in a real callback, not in
the terminal or a standalone Lua interpreter:

```lua
-- From your own already-loaded Game Lua callback, with the probe function
-- previously loaded/defined in the SAME Lua script context:
local world = sm.localPlayer.getWorld()  -- CLIENT ONLY
if world ~= nil then
    smAtlasGroundProbe(world)
end
```

The function checks `world.id == 23` and aborts on mismatch, then casts
short downward rays starting 1 metre above the predicted surface and
ending 2 metres below it. It first filters `terrainSurface`; on a miss,
it checks `allTerrain` to reveal possible terrain asset interceptions.
It logs 15 records prefixed `ATLAS_GROUND,`, plus a metadata line.
`terrainAsset` hits, empty casts and terrain/voxel intersections
with a non-upward normal (`normalWorld.z <= 0.1`) **do not count as
measured standing ground**. Their observations are retained separately.
The current engine reports `voxelTerrain`, while old samples may use
`terrainSurface`. Neither a terrain raycast nor an upward normal proves
walkable character clearance.
**All 15 hits may fail even with a correct world transform** if the
cave collision mask, terrain engine, or ray intervals behave differently.

Collect the complete game log from the correct Scrap Mechanic run.
Atlas can now isolate the newest complete run whose declared world ID and
sample count match the saved plan, and then verify each point's index,
world and coordinates before writing the output. It refuses to merge
multiple probes or silently fall back if the latest matching run fails.

```powershell
# Point Atlas to the Logs directory of your Scrap Mechanic installation.
$logsDir = 'F:\Steam\steamapps\common\Scrap Mechanic\Logs'
sm-atlas tile-ground-extract .\ground_plan.json --logs-dir $logsDir --output .\atlas_ground_hits.log
sm-atlas tile-ground-compare .\ground_plan.json .\atlas_ground_hits.log
sm-atlas tile-ground-compare .\ground_plan.json .\atlas_ground_hits.log --json > .\ground_comparison.json
```

When `--logs-dir` is supplied, Atlas scans only `game*.log` files in
that exact directory (not subdirectories), newest first by file
modification time. The path above is an example from one test Steam
installation; use the actual Logs directory on your machine. Unrelated
logs are skipped. If the newest plan-matching experiment is incomplete
or invalid, extraction fails rather than falling back to an older run.
You can still supply a specific game-log path as the positional argument
instead of `--logs-dir`.

The extraction command never overwrites an existing output, plan or game
log. Repeated captures require a different output filename or explicit
manual cleanup after verifying backups. It requires the generated Lua's
`ATLAS_GROUND_META,world=...,count=...` marker. For legacy logs
without this marker, use `tile-ground-compare` with a known single
run; do not splice repeated raw-log records together.

The comparator refuses data for a different world or an outdated plan,
calculates terrain-height errors and a median vertical offset (which
**must not** be silently interpreted as a constant engine offset),
and reports observed absolute XY gradients separately on each of
three tracks across the critical area. Missing measurements do not
connect neighbouring samples across gaps. None of this determines
player capsule clearance or jump/stair locomotion.

Official API: https://scrapmechanic.com/api/namespace_Game_sm_physics.html
and https://scrapmechanic.com/api/namespace_Game_sm_log.html.
The client World accessor is documented at
https://scrapmechanic.com/api/namespace_Game_sm_localPlayer.html.

## Real-world Drill2 ground measurement (2026-10-08)

In the test save (world 23, node 322, center line x=44.5), we obtained
15/15 valid `voxelTerrain` hit records, including the three 5-sample
horizontal tracks. **Important regression:** an earlier version of
`tile-ground-compare` classified these as `other_or_miss` because it
recognized only `terrainSurface`. The hit data themselves were valid.
With the updated comparator, re-run against the existing
`atlas_ground_hits.log`; no new in-game probing is necessary.

- For x=44.5, y=-107.5..-108.5, the 5 observed Z values were
  81.833336, 81.860001, 81.886673, 81.913338, and 81.940002 m.
- The tentative predicted Z series was 82.1667, 82.4750, 82.7833,
  83.0917, and 83.4000 m.
- Over this 1 m XY distance, observed absolute elevation change was
  ~0.1067 m rather than predicted ~1.2333 m. Adjacent normal Z values
  were strongly upward. This suggests the candidate height interpolation
  is incorrect at this location (not merely a uniform vertical offset).
- After fixing the comparator's `voxelTerrain` classification, the
  actual CLI reported:
  `logged=15/15 terrain_surface=15 non_upward=0 other_or_miss=0`;
  `median_bias=-0.896627m`, `mean_error=-0.893857m`,
  `rmse=0.979018m`, `max_error=1.529997m`,
  `max_after_bias=0.633370m`.
  Track maximum adjacent absolute gradients (left/center/right) were
  `0.106692`, `0.106688` and `0.201752`.
  The substantial residual **after** removal of a constant Z offset is
  evidence of shape/grade disagreement, not just vertical translation.
- Next read-only diagnostic: use `tile-world-probe` with
  `--density-bits 4` on the **test save** and same tile, node and
  edge to see whether the alternative bit hypothesis produces a
  candidate vertical iso-crossing at all. If it fails to produce one,
  that does not prove the four-bit hypothesis globally false.
- The raycasts do not establish player walkability, path continuity,
  overhead clearance, or the correct voxel-density bit packing.

## Offline raw voxel profile alongside verified raycasts

Once the 15 `ATLAS_GROUND,` lines are saved, the *read-only*
`tile-ground-profile` command can inspect the original voxel bytes near
the actual observed standing-surface heights:

```powershell
sm-atlas tile-ground-profile .\ground_plan.json .\atlas_ground_hits.log $tile
sm-atlas tile-ground-profile .\ground_plan.json .\atlas_ground_hits.log $tile --json > .\ground_voxel_profile.json
```

It requires the **same original .tile file** used to generate the anchored
plan. It checks tile UUID, dimensions, saved node rotation/bounds and
world/sample coordinates, then maps observed ground hit XYZ back into
tile-local coordinates. For each nearest integer XY column, it prints
a narrow Z window of **raw bytes, low 4 bits and low 5 bits**, together
with any candidate vertical crossings using the existing midpoint
thresholds (8 for 4 bits and 16 for 5 bits).

These are *diagnostic byte columns*, not the physics engine's mesh.
The exact sample/voxel alignment and spatial interpolation are not
known: a raycast position may depend on multiple voxel neighbours.
A failed 4-bit crossing at the original two endpoints is local evidence
only; it does not refute every possible 4-bit packing or threshold.
Do not interpret matching candidate bytes as proof of walkability.

## Offline 3D trilinear surface hypotheses (no game changes)

The raw byte profiles showed that both 4-bit and 5-bit masks produce
some vertical crossing candidates but disagree with the smooth real
raycast surface. Treat `tile-ground-profile`'s **single nearest XY
column** only as a first diagnostic; ray hits between voxel columns may
depend on their neighbours. A second read-only command explicitly tests
bilinear packed densities in XY followed by a linear Z isocrossing:

```powershell
sm-atlas tile-ground-hypotheses .\ground_plan.json .\atlas_ground_hits.log $tile
sm-atlas tile-ground-hypotheses .\ground_plan.json .\atlas_ground_hits.log $tile --json > .\ground_hypotheses.json
```

This evaluates **16 predeclared candidates**, not a machine-fitted
model: low 4 vs low 5 bits, midpoint thresholds (8/16 respectively)
and all 8 integer/half-voxel origin shifts in X/Y/Z. It searches only
within the original in-game raycast window (predicted Z +1 to -2 m).
For each hit it counts no crossings, one crossing or multiple ambiguous
crossings. Only unambiguous single crossings contribute to RMSE and
bias statistics. Models are ordered by number of covered hits and
uncorrected RMSE, with no guarantee that the first is physically
correct.

**Cautions:** this uses trilinear *scalar field interpolation*, not
verified game triangulation or actual collision geometry. It excludes
unpopulated 0xFF bytes instead of inventing densities, and never
selects whichever crossing is *closest* to the observed result after
seeing the measurement. All 15 calibration samples occupy a tiny patch.
Even an apparent near-perfect match at these coordinates cannot
distinguish different unseen packing or demonstrate a walkable route.
Repeat on distinct tiles/terrain before making any general claims.

## Raw byte forensics anchored to the real cave floor

**Problem:** Choosing a four-, five- or six-bit mask still assumes
that the byte means what our model thinks it means. Previous model
rankings test predicted heights, not the byte encoding itself. The
read-only `tile-ground-byte-audit` command instead examines original
voxel bytes surrounding the **15 already recorded game-raycast hits**.

```powershell
git pull
sm-atlas tile-ground-byte-audit .\ground_plan.json .\atlas_ground_hits.log $tile
sm-atlas tile-ground-byte-audit .\ground_plan.json .\atlas_ground_hits.log $tile --radius 0 --json > .\ground_byte_audit.json
```

It uses the anchored plan and matching tile UUID, rotation, dimensions
and world ID already checked by `tile-ground-profile`. It reads the
same underlying 16³ block records; it does not change them.

The report keeps **unique integer XY voxel columns** instead of counting
repeated raycasts that hit the same raw column as extra independent
byte evidence. It considers the two previously tested vertical origin
shifts (0 and 0.5 voxel), and reads the two recorded voxel bytes
bracketing each *measured* hit Z. With the default `--radius 1`,
neighbouring columns are included for context; their approximate floor
height is borrowed from the closest genuine game hit. Use `--radius 0`
for the strictest comparison, but expect fewer unique columns.

Outputs:

- `recorded_pairs / candidate_columns`: only both-byte-written
  pairs count. A missing or out-of-bounds voxel is never given a
  made-up density.
- `bit transitions`: which of the eight individual raw bits switch
  from 1→0 or 0→1 as we move upward past the observed floor height.
- `bits=4/5/6`: how many byte pairs cross each **assumed midpoint**
  in the expected ground-to-air or the reverse direction, or
  remain on one side. This is a test of the assumption, not proof
  of a mask or true physics.
- `common raw byte pairs`: frequent original hex pairs
  (example: `1F->03`) for investigation without assuming a packing.
- JSON includes every column, nearest actual game hit, local height,
  raw before/after bytes, and record presence for later analysis.

**Crucial limit:** the engine may interpolate across several
neighbouring voxels, use a different grid origin, or build triangles
whose collision positions do not match a two-byte vertical crossing.
A missing apparent 4-bit crossing in one column does **not** disprove
the 4-bit mask. Data from neighbouring columns are not additional
independent game-raycast measurements. No decoder is automatically
chosen or fitted, and this tool does not install game scripts.

The native `sm.voxelTerrainCell.copyTileCellVoxels` API establishes
that the engine can copy voxel data from a tile into a runtime grid,
but does not reveal byte packing or collision triangulation. The
native `sm.terrainTile.getHeightAt` returns a *single* height at
each (x,y) and does not by itself describe a potentially multi-level
underground cave.

Official sources:
- https://scrapmechanic.com/api/namespace_Terrain_sm_voxelTerrainCell.html
- https://scrapmechanic.com/api/namespace_Terrain_sm_terrainTile.html

## Inverse test: what is the density at the real game floor?

The preceding raw-byte audit for Drill2 recorded only **4 unique**
integer XY columns from **15** game-raycast hits (radius 0).
Two columns showed `7F -> 73`, two showed `7F -> 7F`.
On these four columns, two pairs crossed the hypothesized **4-bit**
density midpoint and none crossed the 5- or 6-bit midpoints.
This is a useful clue, **not** proof: the real collision surface may
be interpolated from neighbouring columns, and 15 measured surface
positions are only one small patch.

Instead of finding a candidate surface height and comparing it to
the game, the new **read-only inverse test** samples each hypothesized
3D density field **at the 15 real game hit coordinates themselves**:

```powershell
git pull
sm-atlas tile-ground-isovalue-audit .\ground_plan.json .\atlas_ground_hits.log $tile --include-6-bit
sm-atlas tile-ground-isovalue-audit .\ground_plan.json .\atlas_ground_hits.log $tile --include-6-bit --json > .\ground_isovalue_audit.json
```

Each of the 24 opt-in combinations computes trilinear density at
the actual height of each hit, and also the upward density change
between the bracketing Z layers. It reports:

- `sampled/15`: coverage, excluding missing/unknown neighbouring
  voxel records. Fewer samples must never masquerade as better fit.
- `falling/rising/flat`: number of observed positions where the
  candidate raw density decreases/increases/does not change upward.
  Falling is only a **hypothesis-compatible** direction for a ground
  boundary; it is not proof of the engine's sign convention.
- `midpoint`: the fixed, *assumed* normalized cutoff
  (`8/15`, `16/31`, or `32/63`).
- `observed_median`: the median sampled scalar value at the
  actual game hits; a candidate fixed surface would require its
  density to be near one common cutoff.
- `fixed_error`: mean absolute difference between observed density
  and the *unfitted* half-range cutoff (normalized 0–1).
- `fitted_spread`: mean absolute deviation around the sample median,
  **fitted on the same data** only to diagnose consistency. This is
  never a valid decoder threshold or independent evidence.

If `observed_median` is far from `midpoint` but `fitted_spread`
is small **and** densities fall upward, that motivates investigating
the threshold/coordinate convention. High spread suggests that merely
changing one cutoff cannot explain the 15 hits. A constant solid
region can have zero spread with `flat=15`; that is NOT a surface
model. Even a perfect apparent fit on this patch cannot establish
the actual game's interpolation, triangulation or character clearance.

No game scripts, installed binaries, original saves or ordinary
navigation are modified. This is an investigation of evidence, not
a model automatically selected from 24 candidates.

## Wider in-game ground patch: distinct voxel XY cells

The 2026-10-09 Drill2 raycast-normal comparison found that the
best 15/15 candidate had an angular error of **31.05° overall**
and **32.75° on the 8 samples off candidate grid planes**. Grouping
the raycasts by voxel XY cell gave only **4 represented cells**.
We cannot identify the real geometry algorithm from so few
spatially distinct locations, regardless of how many variations of
bit packing or threshold we score.

Use `tile-ground-grid-plan` to prepare a **separate, unmeasured**
5×5 grid around the centre of the already verified game hits. It
checks the original plan/log against the matching `.tile` UUID,
dimensions, world rotation and two saved tunnel anchors. Each
target uses a different candidate voxel XY column, even with
0.5-voxel origin shifts; points are positioned at fraction
0.31 of each XY voxel to avoid sample-grid seams for **both**
0.0 and 0.5 origins. The grid spacing is one metre in each
direction, for a roughly 4×4 m patch with 25 new raycasts.
These are **new planned targets**, not 25 independent verified
floor hits: some may fall on a wall, miss the terrain or be
outside loaded collision.

```powershell
git pull
sm-atlas tile-ground-grid-plan .\ground_plan.json .\atlas_ground_hits.log $tile --output .\ground_grid_plan.json
sm-atlas tile-ground-lua .\ground_grid_plan.json --output .\atlas_ground_grid.lua
```

The resulting plan has the same verified saved tile placement and
world ID, and is compatible with the existing reversible Survival
ground hook and `tile-ground-normal-audit`. The `--size 3`
or `--size 7` option changes grid width if the intended terrain
corridor is smaller or larger. The command **refuses to overwrite**
an existing plan, original tile, or source log. It does not write
to an installed game file, original save, or Lua script.

**Ray window limitation:** the nearest old *actual game hit Z*
is used as the centre of each new downward ray (+1 m above,
-2 m below, as implemented by the existing Lua fragment).
The tool **does not know** the actual ground height at new
positions. This nearest height is an estimate to aim the
instrument, not proof of the surface or a fitted decoder.
Narrow rays can miss a much higher/lower floor, or encounter
unexpected collision and return a non-floor normal. A missing
hit must remain unknown, not count as an empty voxel.

If you explicitly choose to repeat the game experiment:

1. Close Scrap Mechanic, back up the Survival save, and use the
   existing reversible `tile-ground-survival` **preview** on the
   OLD plan/Lua pair. If the prior hook is still installed,
   run **`--remove` on that same OLD pair first**, before
   attempting to install a different hook.
2. Preview the NEW pair and only then explicitly install the
   new hook. Keep the exact original installation path already
   documented above as `$gameScript`.
3. Enter the anchored underground world **23** and approach
   the measurement area through ordinary gameplay. Collect
   **new probe's game log**. Use `tile-ground-extract` below to
   select the newest complete, plan-matching run; do not merge old
   and new measurements, as sample indices start at zero again.
4. Exit the game and remove the NEW hook using the exact
   NEW plan/Lua pair, restoring the original script.

The steps for the NEW hook, using the same existing
`$gameScript` installation path, are:

```powershell
sm-atlas tile-ground-survival .\ground_grid_plan.json $gameScript --lua .\atlas_ground_grid.lua
# Only after closing game, backing up save and removing any old hook:
sm-atlas tile-ground-survival .\ground_grid_plan.json $gameScript --lua .\atlas_ground_grid.lua --install
# After game capture, close game and remove the new hook:
sm-atlas tile-ground-survival .\ground_grid_plan.json $gameScript --lua .\atlas_ground_grid.lua --remove
```

Once authentic **new** logs have been captured, isolate the matching
experiment and test normal orientation directly on the wider grid:

```powershell
sm-atlas tile-ground-extract .\ground_grid_plan.json --logs-dir $logsDir --output .\atlas_ground_grid_hits.log
sm-atlas tile-ground-compare .\ground_grid_plan.json .\atlas_ground_grid_hits.log
sm-atlas tile-ground-normal-audit .\ground_grid_plan.json .\atlas_ground_grid_hits.log $tile --include-6-bit
```

More distinct ground locations will help distinguish true
decoder/mesher mismatch from artifacts of one tiny patch,
but cannot by themselves prove a unique algorithm.

## Surface orientation vs game physics: no threshold fitting

The preceding `tile-ground-isovalue-audit` measured candidate scalar
values at the same 15 genuine game ground hits. On this Drill2 patch,
several 4-bit candidates had **15/15 falling densities** but their
observed normalized values still varied substantially. A single
adjusted cutoff has **not** been shown to reconstruct the collision
surface or correct our model slopes.

The next read-only diagnostic tests a stronger property: the
**direction** of the raw candidate density gradient at each authentic
game hit, compared with the surface normal returned by
`sm.physics.raycast`. For a genuine smooth isosurface, the gradient
should be perpendicular to the surface. A different constant cutoff
can move an isosurface but **cannot change the field's gradient at a
fixed test point**. Therefore a large orientation mismatch at the
actual game heights cannot be explained by changing only the cutoff
there, under this particular field interpolation.

```powershell
git pull
sm-atlas tile-ground-normal-audit .\ground_plan.json .\atlas_ground_hits.log $tile --include-6-bit
sm-atlas tile-ground-normal-audit .\ground_plan.json .\atlas_ground_hits.log $tile --include-6-bit --json > .\ground_normal_audit.json
```

All variants share the exact existing saved-world tile alignment and
quarter-turn rotation. Instead of choosing a crossing root, this
compares a locally calculated 3D gradient with the *game-reported*
3D normal. It reports:

- `normal_samples=15/15`: model gradients which have all required
  **recorded** neighbouring bytes, nonzero slope and density
  falling upward. Unavailable/flat/reversed samples do not get an
  invented angular score.
- `mean_angle_error_deg` / `max_angle_error_deg`: how far the
  candidate surface normal points away from the game normal in
  degrees. **0° = aligned**; larger is worse. A low angle alone
  still does not establish a correct mesh or a usable route.
- `at_grid_plane`: candidate hits on or extremely near voxel
  sample planes, where a piecewise-linear field can have a sharp
  derivative change. The diagnostic uses symmetric 1 cm
  differences and marks these cases as **less reliable**.
- `non_falling` and `unavailable`: transparent coverage limitations,
  not evidence for or against an unknown real-game density sign.

This is a **diagnostic**, not a decoder or a threshold optimizer.
It uses the same small, spatially correlated real game hits.
The game collision mesh may be triangulated differently from a smooth
density isosurface, in which case even a correct byte interpretation
might not reproduce triangle normals at each exact point.

### Check whether the normal mismatch is a grid-seam artifact

The 2026-10-09 Drill2 run compared all 24 candidate fields with
15 real collision normals. The strongest full-coverage (15/15) candidate
had **31.05°** mean angular error and **7/15** hits on or near
candidate voxel grid planes. A 28.64° candidate checked only 12/15
hits and must not be claimed superior without accounting for coverage.

Grid planes are troublesome because the assumed trilinear field is
only piecewise smooth: its gradient can change abruptly across a plane.
The 1 cm symmetric-difference gradient averages the two sides, which
need not match any physical triangle normal. To avoid mistaking such
an artifact for a decoder failure (or success), the normal audit now
also reports:

- `off_grid=N/15` and `off_grid_mean_deg`: angular errors excluding
  points at or within ~1 cm of **any candidate X, Y, or Z lattice
  plane**. More selective means fewer measurements; never compare
  just the error without its coverage.
- `cells` and `off_grid_cells`: number of **candidate XY voxel
  columns** represented by evaluated hits, and number with at least
  one evaluated off-grid hit. Different lattice origins can change
  which points share a cell.
- `cell_balanced_deg`: mean angle after averaging repeated rays in
  each candidate XY cell, then giving each represented cell equal
  weight. This guards against a dense cluster of near-identical ray
  positions dominating the score, but is **not independent terrain
  validation**.
- `off_grid_cell_deg`: same per-cell balancing using only off-grid
  hits. `None` means no such samples exist, **not** a zero error.
- In JSON, `mean_off_grid_abs_world_grade_error_xy` and the detailed
  `candidate_xy_cells` help distinguish X vs Y slope disagreement.

Use the unchanged command:

```powershell
git pull
sm-atlas tile-ground-normal-audit .\ground_plan.json .\atlas_ground_hits.log $tile --include-6-bit
```

The existing `normal_samples`, unfiltered mean angle, and model
ordering remain unchanged for backwards comparison. All these
figures come from the **same 15 game observations**. Excluding
voxel seams cannot prove that the chosen interpolation or
voxel-byte packing matches Scrap Mechanic's physics mesher.

## Optional six-bit byte-packing experiment

Our initial **16** fixed trilinear test models assume that either 4 or
5 low bits in each old underground `.tile` voxel byte encode density.
The unrelated third-party VoxelTerrain DLL documents a *different*
17×17×17 **runtime serialized voxel format** with 6 density bits and
2 material bits. This is a reason to **test** a 6-bit hypothesis, not
proof that our 16×16×16 old tile records use that format.

We can now run eight additional combinations of half-voxel sample
origins, strictly opt-in. Neither this switch nor these diagnostics
change saves, game files, normal voxel routing, or the legacy defaults:

```powershell
sm-atlas tile-ground-hypotheses .\ground_plan.json .\atlas_ground_hits.log $tile --include-6-bit
sm-atlas tile-ground-slope-audit .\ground_plan.json .\atlas_ground_hits.log $tile --include-6-bit
```

The opt-in comparisons report **24** candidates; without the switch
they continue to report the original **16**. This is not model training.
A candidate that better explains one small patch still needs physical
measurements elsewhere, and even such agreement is not player
walkability proof.

**Byte-reading safeguard:** the experimental reader now tracks
whether every voxel byte actually belongs to a recorded tile block.
A recorded literal `0xFF` is retained as data, whereas an unwritten
volume position remains unavailable for interpolation. This
fixes an internal ambiguity in our *experimental reader*, **not** the
unknown physical meaning of `0xFF` or the game's density packing.

The read-only `tile-ground-hypotheses` and `tile-ground-slope-audit`
commands now report:
- `recorded_FF_voxels`: how many literal `0xFF` bytes are actually
  present in recorded tile blocks, regardless of relevance to the patch;
- `FF_sensitive` per hypothesis: how many *of the observed sample
  positions* produce different candidate crossing heights or counts
  compared with the former FF-as-absent interpretation.

An `FF_sensitive=0` across all candidates means this ambiguity
did **not** cause our earlier predictions for the sampled area;
it does not establish the correct terrain mesh. Different results
require further testing and are not automatic evidence that a new
hypothesis is physically correct.

```powershell
git pull
sm-atlas tile-ground-slope-audit .\ground_plan.json .\atlas_ground_hits.log $tile --include-6-bit
```

The existing navigation candidate-void reader retains its legacy
behavior intentionally; it is not changed by this research-only fix.

Reference: https://scrapmechanictools.com/CustomAPIs/VoxelTerrain/LuaAPI/VoxelDataFormat/

## Height vs slope audit: use normals to avoid a false decoder winner

The test-save world 23 (node 322) hit series has real end-to-end
rises of **0.084282 m, 0.106666 m, 0.154198 m** across three
1.0-metre lanes (negative world Y direction). The lowest raw-height
RMSE hypotheses had much larger predicted rises:

| Model by height RMSE | Lane -0.5 m | Lane 0 m | Lane +0.5 m |
| --- | ---: | ---: | ---: |
| Engine raycast | 0.0843 m | 0.1067 m | 0.1542 m |
| 4-bit origin [0, 0.5, 0.5] | 0.9969 m | 0.9943 m | 0.9394 m |
| 5-bit origin [0, 0.5, 0] | 1.0761 m | 1.0729 m | 1.0604 m |

An independent consistency check: on the centre lane's measured
quarter-metre segment (samples 6 to 7), observed directional grade
is +0.106688 m/m. The local hit normal at index 7 has
`ny=0.105379, nz=0.987928`, implying
`dz/d(-y) = ny/nz ~= 0.106667`. This is close evidence of a real
locally shallow patch; normals and height differences on other
segments may vary as the collision triangles change.

`tile-ground-slope-audit` examines **all 16 candidate models** by
the absolute error in end-to-end lane rise, not by proximity of raw
heights. It also calculates the grade from nearby raycast normal
vectors and adjacent hit heights:

```powershell
sm-atlas tile-ground-slope-audit .\ground_plan.json .\atlas_ground_hits.log $tile
sm-atlas tile-ground-slope-audit .\ground_plan.json .\atlas_ground_hits.log $tile --json > .\ground_slope_audit.json
```

This audit is read-only. Models whose endpoint root is ambiguous or
missing do not get an invented slope score. Its ranking tests agreement
**only on these existing 15 observations**. Additional independent
terrain patches and actual walking/capsule tests will be needed to
validate a reusable walkability decoder.

### Why matching total rise is not enough

A one-metre track with equal start/end heights can still contain steep
interior bumps. The legacy `models_ranked_by_rise_error` output therefore
remains available for comparison, but is **not** sufficient to validate
surface shape. The new `models_ranked_by_local_grade_error` output
compares each consecutive pair of game-hit heights with the candidate
pair at the same XY locations. Segments also report disagreement
against directional slopes inferred from game surface normals.

- `segments_scored / measured_segments` shows valid coverage; a model
  with missing or multiple candidate crossings must **not** receive
  invented interpolated grades across those gaps.
- `mean_absolute_local_grade_error` is the signed directional grade
  mismatch in metres of vertical rise per horizontal metre, averaged
  as an absolute difference (dimensionless m/m). A constant Z bias
  cancels, while a wrong interior shape is exposed.
- `mean_absolute_normal_grade_error` compares the same candidate
  slopes with normals derived from real physics hits; this is a
  separate consistency check, not a second independent terrain dataset.
- Results are listed with segment coverage first and local-grade
  error second. A low error on a small subset **must not** outrank
  physical evidence from more extensive, independent measurement.

Neither the normal-based nor point-height-based grade is an engine
walkability constraint. These measurements are from the *same* small
Drill2 patch used to investigate the hypotheses; no hold-out
validation has yet been performed.

### Two-axis audit from the existing 3×5 game-raycast patch

The same 15 real in-game hits occupy three parallel tracks at five
fractions each. In addition to the 12 consecutive **along-track** edges,
the audit now evaluates up to **10 cross-track edges** between adjacent
tracks at matching fractions. The cross-track measurements are horizontal
0.5 m spans in world X for this particular saved tile placement.
The rank `models_ranked_by_patch_grade_error` covers both X and Y
directional slopes, reporting along-track, cross-track and pooled errors.

Run the existing command again after updating the checkout:

```powershell
git pull
sm-atlas tile-ground-slope-audit .\ground_plan.json .\atlas_ground_hits.log $tile
sm-atlas tile-ground-slope-audit .\ground_plan.json .\atlas_ground_hits.log $tile --json > .\ground_slope_2d.json
```

This makes a **transverse-tilt failure detectable** even when the model
matches every along-track rise: a candidate may add a different
constant height to each of the three lanes, preserving all 12
longitudinal grades while getting all 10 transverse slopes wrong.

The output reports the count of **valid measured adjacent edges** and
the count of unambiguous candidate roots at both ends. A model cannot
silently bridge missing hits, skip an intervening lane, or select a
convenient root from multiple candidates. Ranking gives coverage first,
then the mean absolute 2D slope error, and still does **not** accept a
model as a verified decoder. These **22 edges are derived from the same
15 sample positions**; they are not 22 independent game measurements.
Normal vectors come from the same raycasts and can disagree with
finite differences across collision-triangle boundaries.

Equality of longitudinal and end-to-end mean errors can result from
same-signed residual grades over uniformly spaced edges. It is **not**
evidence of twelve independent confirmations of a candidate. The
expanded transverse check directly measures a second spatial direction.

### Distinguish consistent tilt error from incorrect surface shape

A model can be wrong in two very different ways:

1. It can have a nearly **constant extra tilt** across the patch,
   producing very similar signed errors on adjacent edges.
2. It can have the **wrong local bumps**, with some slope errors
   positive and others negative, even when total rise matches.

The read-only audit adds `along_direction_bias` and
`cross_direction_bias` for each model. The CLI prints these for the
highest-ranked coverage-first candidate:

- `game_mean`: measured mean **signed** grade in the direction of
  the recorded edge (world Y decreasing for along, world X increasing
  for cross in this Drill2 measurement).
- `model_mean`: model's mean signed grade in the same direction.
- `mean_error`: mean(model grade - measured grade).
- `error_after_tilt_diagnostic`: mean absolute error left *after
  subtracting that mean error* from the same set of grade residuals.

The last number is deliberately named **diagnostic**: subtracting a
mean error here is in-sample arithmetic, not an authorized correction
to the surface, game collision, transform, or voxel decoder. A low
residual means the measured mismatch resembles a constant plane tilt
on this tiny region; it does not establish the cause or generalize to
other terrain. A high residual means a uniform tilt alone would not
explain the local shape mismatch. A missing or ambiguous crossing
remains unscored, with `null` fields if no edges are valid.

Do **not** select or validate a model using these corrected-in-sample
diagnostics. Independent raycast patches and geometry interpretation
remain necessary.

## Diagnosing a hook that shows no HUD

In the October 8 game log, the Game state loaded and the runtime emitted
other `[Lua]` messages, but there were no `ATLAS_GROUND` markers.
That is **not enough** to assert that the hook ran. New hooks now emit
two independent, one-time diagnostics:

- `ATLAS_GROUND_BOOT,file_loaded,world=23` means the modified
  `SurvivalGame.lua` was executed (module top level).
- `ATLAS_GROUND_HOOK,callback_entered,world=23` means the wrapped
  `client_onUpdate` callback started, **before** the original update
  function is forwarded.
- `ATLAS_GROUND_HOOK,ready,world=23,radius=40` means the original
  client update returned and the Atlas HUD/probe logic was reached.

With none of these logs, inspect whether the installed script path is
being loaded at all; with boot but no callback, inspect Game callback
registration; with callback but no ready, look for an error in the
original callback. A boot marker alone is not evidence of running
raycasts or correct world coordinates.

**Scrap Mechanic 1.0 (2026) script cache caveat:** Steam and Reddit
players report that vanilla Survival can run cached Lua instead of newly
modified `.lua` files. The `-dev` launch option forces script reloading
in documented workflows; it also changes engine behavior and can prevent
achievements. This is a **hypothesis**, not proof that a particular user's
installed file was skipped. Before another test:

1. Check that the *installed* `SurvivalGame.lua` contains both
   `ATLAS_GROUND_BOOT` and `ATLAS_GROUND_HOOK,callback_entered`. If not,
   it contains an old version; remove it, update Atlas, run tests, reinstall
   with the game shut down.
2. If these markers are present but absent from the **newest run's** log,
   test with Steam launch option `-dev` **only on a verified test-save
   copy**, without opening the original world. Do not modify
   `g_survivalDev` or enable cheat commands as part of the experiment.
3. Close the game, inspect the new log, **remove `-dev` from Steam** and
   uninstall the Atlas hook using `--remove` before returning to normal
   gameplay.

Do not delete game cache files or verify/reinstall all Steam game files
as a first troubleshooting step; those operations can overwrite other
local modifications and should require a separate rollback plan.
References:
- https://scrapmechanic.fandom.com/wiki/Launch_options
- https://www.reddit.com/r/ScrapMechanic/comments/1v9tr1i/how_to_edit_loot_in_survival/

When upgrading from an older installed hook: close the game, use
`tile-ground-survival ... --remove` with the existing plan and Lua,
`git pull`, then `pytest` before reinstalling. This is not an
automatic game-file update. Do NOT enable `-dev` to troubleshoot
without understanding its possible save/gameplay consequences.

## Guide from the saved Mining Hub portal (optional)

The regular HUD shows only `need world 23` while the player is in
another world. An opt-in variant can show **the actual XYZ in the hub,
straight-line distance and signed coordinate differences** to a saved
portal entrance; once in the target world, the same hook switches to
the cave target. The entrance must be derived from the *same save copy*
as the raycast plan.

First, **close the game completely** and remove any installed version
of the hook, then compare the script to the known clean pre-install
backup. Only if hashes match, update and run tests. The copy of the
save remains separate from the main save.

```powershell
sm-atlas tile-ground-survival .\ground_plan.json $gameScript --lua .\atlas_ground_probe.lua --remove
# Verify against the exact clean .bak made before installing.
git pull
pytest
sm-atlas portal-probe $testSave --id 67
sm-atlas tile-ground-survival .\ground_plan.json $gameScript --lua .\atlas_ground_probe.lua --navigation-save $testSave --portal-id 67
sm-atlas tile-ground-survival .\ground_plan.json $gameScript --lua .\atlas_ground_probe.lua --navigation-save $testSave --portal-id 67 --install
```

`--navigation-save` and `--portal-id` must be specified together,
and the portal must be decoded with verified world IDs/coordinates and
lead to the raycast plan world. The program **reads** the Portal data
from that save; it doesn't write to any `.db`. The preview is not an
installation. Uninstall uses the ordinary `--remove` command (without
navigation flags).

For this specific saved world, the known portal **#67** connects
Mining Hub (world 12) to Drill2 (world 23). The Mining Hub portal
approach is around `(-96.013, 157.189, 69.086)`; it is **not** a
guaranteed entrance button or a wall-free path. The new HUD in world
12 reads like `Atlas W12 XYZ ... | portal 67 120m | dX... dY... dZ...`.
Distance is direct 3D Euclidean distance, **not** walkable path
length. When world 23 is entered, the HUD automatically switches
to the saved cave's raycast location near `(44.5,-108,82.8)`.

Scrap Mechanic 1.0 may require the launch option `-dev` for patched
Lua code to be loaded. This option may change gameplay and disable
achievements: test **only** on `ATLAS_TEST`, then remove `-dev` and
the installed hook before returning to the main game.

## Finding the actual in-game world and location

In `--world 23`, **23 is a unique saved game-world ID, not the
twenty-third dungeon floor**. To read the type and level from *your*
save:

```powershell
sm-atlas worlds $save | Select-String '^\[23\]' -Context 0,3
sm-atlas underground-tunnels $save --world 23
```

For the previously examined save, world 23 is
`UndergroundWorldDrill2`, label `undergroundworld_drill_02`,
with generation parameter `depth=6`. This is **not floor 23** and
`depth=6` is not automatically the count of accessible elevator floors.
Portal #67 links world 12 (Mining Hub) to world 23, arriving near
`(31.987, 39.189, 74.086)`. This is the saved entry to the target
underground world.

To view Atlas's already available *candidate* 2D route from the
world's elevator to the specific saved passage node 322:

```powershell
sm-atlas underground-route $save --world 23 --node 322
sm-atlas underground-route-map $save --world 23 --node 322 --output .\drill2_to_322.svg
Invoke-Item .\drill2_to_322.svg
```

The resulting SVG is a structural schematic (candidate graph),
**not an in-game minimap or a confirmed traversable route**.

Inspect the `depth` / `Depth` value and the world path. The examined
`drill2_tunnelpocket_small_passage_08_2x3x2.tile` comes from
`Drill2`; that filename alone is not proof of the exact saved-world
depth. You normally enter underground worlds through the mine and
progress to deeper levels via the in-game mine elevator. A save may
assign different world IDs.

Game World coordinates are *not* coordinates on Scrap Mechanic's
ordinary map. A player cannot type `44.5, -108, 83` in a vanilla map
and get a route. To help, the opt-in Survival hook prints a compact
alert every 5 seconds: the current world ID; and, in world 23, the
player's XYZ, 3D straight-line distance to the target, and differences
(`dX dY dZ`). Reduce the distance by moving toward the target,
but obey real caves/walls — straight-line geometry is not a walkable
route or a compass navigation guarantee. This HUD is only available
in hook versions installed after the HUD change.

**If an earlier Atlas hook is already installed**, exit Scrap Mechanic,
run `--remove` with the exact original JSON/Lua pair before pulling
or installing a new hook, update the repo, and then `--install` again.
Do not append a second hook on top of an existing one.

## Opt-in reversible Survival script hook

**This step edits an installed game script only when you explicitly run
`--install`. Close Scrap Mechanic first, and back up your Survival
save as well. Modifying installed game files can affect achievements,
multiplayer compatibility, updates and other mods. It is not as isolated as
running a standalone Custom Game.**

Atlas now has a reversible helper for its generated ground probe:

```powershell
$gameScript = 'F:\Steam\steamapps\common\Scrap Mechanic\Survival\Scripts\game\SurvivalGame.lua'

# Check that the actual game script is present; this does not change it.
Test-Path $gameScript
sm-atlas tile-ground-survival .\ground_plan.json $gameScript --lua .\atlas_ground_probe.lua

# Only after fully quitting Scrap Mechanic and backing up the save:
sm-atlas tile-ground-survival .\ground_plan.json $gameScript --lua .\atlas_ground_probe.lua --install
```

`--install` first creates a timestamped
`SurvivalGame.lua.sm-atlas-*.bak`, then appends a uniquely marked
experimental Lua block. It wraps the existing `SurvivalGame.client_onUpdate`
without deleting the original callback.

The hook logs `ATLAS_GROUND_HOOK,ready,world=23,radius=40` after
the Game client begins updating. It also displays current world ID and
a navigation status alert every five seconds (using
`sm.gui.displayAlertText`). When the local player enters **world 23**
and is within **40 m** of the sampled target (roughly world
`(44.5,-108,82.8)`), it waits two seconds, then runs the ground probe
**once per loaded Game script**. There is no teleportation and no auto
travel; reach the underground area by ordinary gameplay. A player
approaching a remote chunk may still need to wait for terrain loading
or retry by relaunching; zero raycast hits is not negative geometry
evidence.

Recent Scrap Mechanic patch notes locate game logs in its `Logs`
directory. For this Steam installation, search:

```powershell
Get-ChildItem 'F:\Steam\steamapps\common\Scrap Mechanic\Logs' -File |
    Sort-Object LastWriteTime -Descending | Select-Object -First 5

# After the probe has run, replace this path with the correct recent log:
$gameLog = 'F:\Steam\steamapps\common\Scrap Mechanic\Logs\<actual-log-name>'
Get-Content $gameLog | Select-String 'ATLAS_GROUND,' |
    ForEach-Object { $_.Line } | Set-Content .\atlas_ground_hits.log

sm-atlas tile-ground-compare .\ground_plan.json .\atlas_ground_hits.log
```

**Remove the hook after capturing the logs. Exit the game first:**

```powershell
sm-atlas tile-ground-survival .\ground_plan.json $gameScript --lua .\atlas_ground_probe.lua --remove
```

`--remove` first creates another backup, then deletes only the exact
SM Atlas marked block; unrelated user edits to the rest of the Lua file
are not overwritten. If code appears after the managed block, removal
refuses to proceed rather than deleting it. The original backup is never
silently erased. Restart the game after install or removal.

Both the dry-run mode and every generated raycast source are diagnostic
and untested inside the user's actual installation. Do not use the
hook in a multiplayer session or on an irreplaceable save.

## Safeguards

- Do not modify original saves or game binaries.
- Do not insert experimental routes into normal underground navigation.
- The separately documented 2-material-bit/6-density-bit serialized format
  of the third-party VoxelTerrain DLL does not establish the format of
  our original underground .tile files.
- A render mesh from another tool also need not match game collisions.

Only real physics observations can validate or refute our predicted
bottleneck and guide changes to the production navigation algorithm.
