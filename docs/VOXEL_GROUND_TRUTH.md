# Verification against Scrap Mechanic's actual terrain collision

**Status: proposed in-game measurement, not performed.** Neither Atlas's
five-bit density hypothesis nor its fractional-height iso-surface has been
verified against the engine's collision mesh.

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
    if not hit or result.type ~= "terrainSurface" then
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
sm-atlas tile-world-probe $save $tile --world 23 --node 322 --edge "4,35,19" "3,35,20" --json > .\ground_plan.json
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
`terrainAsset` hits or empty casts **do not count as measured ground**.
**All 15 hits may fail even with a correct world transform** if the
cave collision mask, terrain engine, or ray intervals behave differently.

Collect the 15 `ATLAS_GROUND,` lines from the actual game log, optionally
including normal log prefixes, into `atlas_ground_hits.log`. You can
filter an existing game log with PowerShell (replace `$gameLog` with the
actual log file path):

```powershell
Get-Content $gameLog | Select-String "ATLAS_GROUND," |
    ForEach-Object { $_.Line } | Set-Content .\atlas_ground_hits.log

sm-atlas tile-ground-compare .\ground_plan.json .\atlas_ground_hits.log
sm-atlas tile-ground-compare .\ground_plan.json .\atlas_ground_hits.log --json > .\ground_comparison.json
```

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

## Safeguards

- Do not modify original saves or game binaries.
- Do not insert experimental routes into normal underground navigation.
- The separately documented 2-material-bit/6-density-bit serialized format
  of the third-party VoxelTerrain DLL does not establish the format of
  our original underground .tile files.
- A render mesh from another tool also need not match game collisions.

Only real physics observations can validate or refute our predicted
bottleneck and guide changes to the production navigation algorithm.
