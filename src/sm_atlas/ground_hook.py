"""Reversible opt-in SurvivalGame.lua hook for a prepared ground raycast.

No file is edited without an explicit install/remove mode; backups are
always created before modification. This is diagnostic tooling only.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import re
import shutil
import tempfile

from .ground_truth import _validated_ground_plan, render_ground_probe_lua


BEGIN = "-- SM_ATLAS_GROUND_BEGIN (experimental, managed by sm-atlas)"
END = "-- SM_ATLAS_GROUND_END (experimental, managed by sm-atlas)"


def build_survival_hook(plan: dict) -> str:
    """Self-contained generated Lua and one-shot existing-callback wrapper."""
    world_id, samples = _validated_ground_plan(plan)
    x = sum(float(s["world_xy"][0]) for s in samples) / len(samples)
    y = sum(float(s["world_xy"][1]) for s in samples) / len(samples)
    z = sum(float(s["estimated_surface_world_z"]) for s in samples) / len(samples)

    lua = render_ground_probe_lua(plan).rstrip()
    callback = f"""
-- Wrap the existing game's client callback without changing its behaviour.
-- Only execute ONCE after the local player is near this cave area.
-- No save mutations, teleportation, or persistent player state.
local atlasOldClientOnUpdate = SurvivalGame.client_onUpdate
function SurvivalGame.client_onUpdate(self, dt)
    if atlasOldClientOnUpdate ~= nil then
        atlasOldClientOnUpdate(self, dt)
    end
    if not self.atlasGroundHookReadyLogged then
        self.atlasGroundHookReadyLogged = true
        sm.log.info("ATLAS_GROUND_HOOK,ready,world={world_id},radius=40")
    end
    if self.atlasGroundDidRun then return end
    local world = sm.localPlayer.getWorld()
    if world == nil or world.id ~= {world_id} then return end
    local playerPos = sm.localPlayer.getPosition()
    if playerPos == nil then return end
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
    return BEGIN + "\n" + lua + "\n" + callback.strip() + "\n" + END + "\n"


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
        chunk = build_survival_hook(plan).replace(
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
