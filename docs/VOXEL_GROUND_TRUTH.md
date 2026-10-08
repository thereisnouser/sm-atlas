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
