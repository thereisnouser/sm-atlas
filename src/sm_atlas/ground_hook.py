"""Reversible opt-in SurvivalGame.lua hook for a prepared ground raycast.

No file is edited without an explicit install/remove mode; backups are
always created before modification. This is diagnostic tooling only.
"""
from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import os
import re
import shutil
import tempfile

from .ground_truth import _validated_ground_plan, render_ground_probe_lua
from .database import SaveDatabase
from .portals import probe_portals


BEGIN = "-- SM_ATLAS_GROUND_BEGIN (experimental, managed by sm-atlas)"
END = "-- SM_ATLAS_GROUND_END (experimental, managed by sm-atlas)"


@dataclass(frozen=True)
class PortalEntrance:
    """Saved portal's approach side in a different world from the target."""

    portal_id: int
    world_id: int
    xyz: tuple[float, float, float]


def load_portal_entrance(
    save: str | Path, *, destination_world_id: int, portal_id: int,
) -> PortalEntrance:
    """Resolve a hub-side destination from the saved Portal table, read-only.

    World IDs and portal positions are specific to a save. Do not hardcode
    them as globally applicable coordinates or assume portal approach is
    a straight-line navigable player path.
    """
    if destination_world_id <= 0 or portal_id <= 0:
        raise ValueError("destination world ID and portal ID must be positive")
    candidates = probe_portals(
        SaveDatabase(Path(save)), portal_id=portal_id,
    )
    if len(candidates) != 1:
        raise ValueError(f"portal {portal_id} not found in the specified save")
    portal = candidates[0]
    decoded = portal.decoded
    if (
        portal.decoded_matches_columns is not True
        or decoded is None
        or decoded.position_b is None
    ):
        raise ValueError(
            f"portal {portal_id} has no verified two-sided world positions"
        )
    if portal.world_id_b == destination_world_id:
        entry_world, entry_xyz = portal.world_id_a, decoded.position_a
    elif portal.world_id_a == destination_world_id:
        entry_world, entry_xyz = portal.world_id_b, decoded.position_b
    else:
        raise ValueError(
            f"portal {portal_id} does not lead to world {destination_world_id}"
        )
    if entry_world <= 0 or entry_world == destination_world_id:
        raise ValueError("portal entrance world is not a different saved world")
    if not all(isfinite(v) for v in entry_xyz):
        raise ValueError("portal entrance coordinates are not finite")
    return PortalEntrance(
        portal_id=portal_id,
        world_id=entry_world,
        xyz=tuple(float(v) for v in entry_xyz),
    )


def build_survival_hook(
    plan: dict, *, entrance: PortalEntrance | None = None,
) -> str:
    """Self-contained generated Lua and one-shot existing-callback wrapper."""
    world_id, samples = _validated_ground_plan(plan)
    x = sum(float(s["world_xy"][0]) for s in samples) / len(samples)
    y = sum(float(s["world_xy"][1]) for s in samples) / len(samples)
    z = sum(float(s["estimated_surface_world_z"]) for s in samples) / len(samples)

    lua = render_ground_probe_lua(plan).rstrip()
    other_world_hud = f'''sm.gui.displayAlertText(string.format(
                "Atlas: world %d | need world {world_id} (Drill2)", worldId
            ), 4.0, false)'''
    if entrance is not None:
        if entrance.portal_id <= 0 or entrance.world_id <= 0:
            raise ValueError("invalid portal navigation identifiers")
        if entrance.world_id == world_id:
            raise ValueError("portal navigation must begin in another world")
        if len(entrance.xyz) != 3 or not all(
            isfinite(v) for v in entrance.xyz
        ):
            raise ValueError("portal navigation coordinates must be finite")
        px, py, pz = entrance.xyz
        other_world_hud = f'''if worldId == {entrance.world_id} and playerPos ~= nil then
                local deltaX = {px:.6f} - playerPos.x
                local deltaY = {py:.6f} - playerPos.y
                local deltaZ = {pz:.6f} - playerPos.z
                local distance = math.sqrt(
                    deltaX * deltaX + deltaY * deltaY + deltaZ * deltaZ
                )
                sm.gui.displayAlertText(string.format(
                    "Atlas W%d XYZ %.0f %.0f %.0f | portal {entrance.portal_id} %.0fm | dX%+.0f dY%+.0f dZ%+.0f",
                    worldId, playerPos.x, playerPos.y, playerPos.z,
                    distance, deltaX, deltaY, deltaZ
                ), 4.0, false)
            else
                sm.gui.displayAlertText(string.format(
                    "Atlas: world %d | need world {world_id} (Drill2)", worldId
                ), 4.0, false)
            end'''
    callback = f"""
-- Wrap the existing game's client callback without changing its behaviour.
-- Only execute ONCE after the local player is near this cave area.
-- No save mutations, teleportation, or persistent player state.
local atlasOldClientOnUpdate = SurvivalGame.client_onUpdate
function SurvivalGame.client_onUpdate(self, dt)
    if not self.atlasGroundHookSawUpdate then
        self.atlasGroundHookSawUpdate = true
        sm.log.info("ATLAS_GROUND_HOOK,callback_entered,world={world_id}")
    end
    if atlasOldClientOnUpdate ~= nil then
        atlasOldClientOnUpdate(self, dt)
    end
    if not self.atlasGroundHookReadyLogged then
        self.atlasGroundHookReadyLogged = true
        sm.log.info("ATLAS_GROUND_HOOK,ready,world={world_id},radius=40")
    end
    local world = sm.localPlayer.getWorld()
    local worldId = (world ~= nil) and world.id or -1
    local playerPos = sm.localPlayer.getPosition()
    -- User-facing orientation: identify the saved world and the player's
    -- actual XYZ; don't require guessing where world 23 is located.
    self.atlasGroundHudClock = (self.atlasGroundHudClock or 4.9) + dt
    if self.atlasGroundHudClock >= 5.0 then
        self.atlasGroundHudClock = 0
        if worldId ~= {world_id} then
            {other_world_hud}
        elseif playerPos ~= nil then
            local deltaX = {x:.6f} - playerPos.x
            local deltaY = {y:.6f} - playerPos.y
            local deltaZ = {z:.6f} - playerPos.z
            local distance = math.sqrt(
                deltaX * deltaX + deltaY * deltaY + deltaZ * deltaZ
            )
            sm.gui.displayAlertText(string.format(
                "Atlas W%d | XYZ %.0f %.0f %.0f | goal %.0fm | dX%+.0f dY%+.0f dZ%+.0f",
                worldId, playerPos.x, playerPos.y, playerPos.z,
                distance, deltaX, deltaY, deltaZ
            ), 4.0, false)
        else
            sm.gui.displayAlertText(
                "Atlas: world {world_id} | waiting for player position", 4.0, false
            )
        end
    end
    if self.atlasGroundDidRun then return end
    if world == nil or worldId ~= {world_id} or playerPos == nil then return end
    local dx = playerPos.x - {x:.6f}
    local dy = playerPos.y - {y:.6f}
    local dz = playerPos.z - {z:.6f}
    if dx * dx + dy * dy + dz * dz > 1600.0 then
        self.atlasGroundNearbySeconds = 0
        return
    end
    self.atlasGroundNearbySeconds = (self.atlasGroundNearbySeconds or 0) + dt
    if self.atlasGroundNearbySeconds < 2.0 then return end
    self.atlasGroundDidRun = true
    local ok, err = pcall(smAtlasGroundProbe, world)
    if not ok then
        sm.log.error("ATLAS_GROUND_ERROR," .. tostring(err))
    end
end
"""
    boot = (
        'pcall(function() sm.log.info("ATLAS_GROUND_BOOT,file_loaded,world='
        + str(world_id) + '") end)'
    )
    return BEGIN + "\n" + boot + "\n" + lua + "\n" + callback.strip() + "\n" + END + "\n"


def _check_game_script(data: bytes) -> None:
    if b"\x00" in data:
        raise ValueError("game script appears binary/UTF-16; refusing to patch")
    if not (
        b"SurvivalGame = class(" in data
        and b"function SurvivalGame.client_onUpdate" in data
    ):
        raise ValueError(
            "target does not look like the expected SurvivalGame.lua; "
            "refusing to modify an unknown game script"
        )
    if re.search(rb"(?m)^return\s+SurvivalGame\s*$", data):
        raise ValueError(
            "target returns SurvivalGame at top level; safe hook point "
            "needs explicit review"
        )


def _atomic_replace(target: Path, contents: bytes) -> None:
    staged = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=".sm-atlas-",
            suffix=".tmp", delete=False,
        ) as fd:
            staged = Path(fd.name)
            fd.write(contents)
        os.replace(staged, target)
    finally:
        if staged is not None and staged.exists():
            staged.unlink()


def survival_hook_operation(
    game_script: str | Path,
    plan: dict,
    *,
    lua_text: str,
    action: str = "preview",
    entrance: PortalEntrance | None = None,
) -> dict[str, object]:
    """Preview, install, or remove an Atlas hook in a vanilla Game script.

    Install/remove must be explicitly selected by the caller. Uninstall
    removes only our uniquely marked appended fragment; prior copies of
    user-modified game scripts remain in timestamped backups.
    """
    if action not in ("preview", "install", "remove"):
        raise ValueError("action must be preview, install or remove")
    if lua_text != render_ground_probe_lua(plan):
        raise ValueError(
            "Lua file differs from the JSON plan; regenerate with "
            "tile-ground-lua to avoid mismatched coordinates"
        )

    target = Path(game_script).expanduser().resolve()
    if target.name.lower() != "survivalgame.lua":
        raise ValueError(
            "target must be the exact SurvivalGame.lua game script"
        )
    data = target.read_bytes()
    begin = BEGIN.encode("ascii")
    end = END.encode("ascii")
    beginning = data.find(begin)
    ending = data.find(end)
    if (beginning >= 0) != (ending >= 0):
        raise ValueError("incomplete SM Atlas marker; refusing to edit")
    if beginning >= 0 and ending <= beginning:
        raise ValueError("SM Atlas end marker is before begin marker")
    if data.count(begin) > 1 or data.count(end) > 1:
        raise ValueError("multiple SM Atlas markers; manual review needed")

    if action == "preview":
        if beginning < 0:
            _check_game_script(data)
        return {
            "action": "preview",
            "target": str(target),
            "already_installed": beginning >= 0,
            "will_modify": False,
            "needs_game_restart": True,
            "note": "Use explicit --install to patch, --remove to undo.",
        }

    if action == "install":
        if beginning >= 0:
            raise ValueError("SM Atlas hook already installed")
        _check_game_script(data)
        line_end = "\r\n" if b"\r\n" in data else "\n"
        separator = (
            b"" if not data or data.endswith((b"\n", b"\r"))
            else line_end.encode("ascii")
        )
        chunk = build_survival_hook(plan, entrance=entrance).replace(
            BEGIN, BEGIN + f" separator={int(bool(separator))}", 1,
        ).replace("\n", line_end)
        new_contents = data + separator + chunk.encode("utf-8")
    else:
        if beginning < 0:
            raise ValueError("SM Atlas hook is not installed")
        tail = ending + len(end)
        if data[tail:tail + 2] == b"\r\n":
            tail += 2
        elif data[tail:tail + 1] == b"\n":
            tail += 1
        # The segment added by install must be the *last* file content.
        # Refuse to delete unrelated updates after the marked section.
        if data[tail:].strip():
            raise ValueError(
                "there is content after the installed Atlas hook; "
                "manual review required"
            )
        first_line_end = data.find(b"\n", beginning)
        marker_line = data[
            beginning:first_line_end if first_line_end >= 0 else len(data)
        ].decode("ascii").strip()
        if "separator=1" in marker_line:
            # Remove the extra CRLF/LF introduced for a script whose
            # original final line had no trailing newline.
            prefix_end = beginning
            if data[:beginning].endswith(b"\r\n"):
                prefix_end -= 2
            elif data[:beginning].endswith(b"\n"):
                prefix_end -= 1
            else:
                raise ValueError("marked separator missing; manual review")
        elif "separator=0" in marker_line:
            prefix_end = beginning
        else:
            raise ValueError(
                "unknown SM Atlas marker version; manual review required"
            )
        new_contents = data[:prefix_end]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = target.with_name(f"{target.name}.sm-atlas-{stamp}.bak")
    shutil.copy2(target, backup)
    try:
        _atomic_replace(target, new_contents)
    except Exception:
        # Backup remains available even if the atomic replacement fails.
        raise
    return {
        "action": action,
        "target": str(target),
        "backup": str(backup),
        "already_installed": beginning >= 0,
        "will_modify": True,
        "needs_game_restart": True,
        "note": (
            "Exit the game completely before editing the script. "
            "The diagnostic runs once per game-script instance within "
            "40 m of the specified cave location, only in the target world."
        ),
    }
