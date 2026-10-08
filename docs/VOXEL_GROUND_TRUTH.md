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

## Coordinate transform is currently unresolved

Voxel and socket coordinates in Atlas are **tile-local**. They are not
world-space positions. Database world ID 23 is *not* a World userdata.
Before using this in-game raycast:

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

## Safeguards

- Do not modify original saves or game binaries.
- Do not insert experimental routes into normal underground navigation.
- The separately documented 2-material-bit/6-density-bit serialized format
  of the third-party VoxelTerrain DLL does not establish the format of
  our original underground .tile files.
- A render mesh from another tool also need not match game collisions.

Only real physics observations can validate or refute our predicted
bottleneck and guide changes to the production navigation algorithm.
