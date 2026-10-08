from __future__ import annotations

import json

import pytest

from sm_atlas.ground_hook import (
    BEGIN,
    END,
    build_survival_hook,
    survival_hook_operation,
)


def _plan() -> dict:
    return {
        "world_id": 23,
        "alignment": {
            "status": "two_or_more_independent_tunnel_anchors",
            "distinct_sockets": 4,
            "distinct_tunnels": 4,
        },
        "critical_edge": {
            "world_samples": [{
                "world_xy": [44.5, -108.0],
                "estimated_surface_world_z": 83.0,
                "fraction": 0.5,
                "lateral_offset_m": 0,
            }],
        },
    }


def _source(*, trailing_newline: bool = True) -> bytes:
    value = (
        b"SurvivalGame = class( nil )\r\n"
        b"function SurvivalGame.client_onUpdate( self, dt )\r\n"
        b"    self.counter = (self.counter or 0) + 1\r\n"
        b"end"
    )
    return value + (b"\r\n" if trailing_newline else b"")


@pytest.mark.parametrize("with_newline", [True, False])
def test_survival_hook_dry_run_install_and_remove_preserves_bytes(
    tmp_path,
    with_newline: bool,
) -> None:
    from sm_atlas.ground_truth import render_ground_probe_lua

    path = tmp_path / "SurvivalGame.lua"
    original = _source(trailing_newline=with_newline)
    path.write_bytes(original)
    plan = _plan()
    lua = render_ground_probe_lua(plan)

    dry_run = survival_hook_operation(path, plan, lua_text=lua)
    assert dry_run["action"] == "preview"
    assert not dry_run["will_modify"]
    assert path.read_bytes() == original

    installed = survival_hook_operation(
        path, plan, lua_text=lua, action="install",
    )
    assert installed["will_modify"]
    assert installed["backup"]
    from pathlib import Path

    assert Path(installed["backup"]).read_bytes() == original
    patched = path.read_text(encoding="utf-8")
    assert BEGIN in patched and END in patched
    assert "local atlasOldClientOnUpdate = SurvivalGame.client_onUpdate" in patched
    assert "atlasOldClientOnUpdate(self, dt)" in patched
    assert "world.id ~= 23" in patched
    assert "ATLAS_GROUND_HOOK,ready,world=23,radius=40" in patched
    assert "if self.atlasGroundDidRun then return end" in patched

    preview_installed = survival_hook_operation(path, plan, lua_text=lua)
    assert preview_installed["already_installed"]
    assert not preview_installed["will_modify"]

    with pytest.raises(ValueError, match="already installed"):
        survival_hook_operation(path, plan, lua_text=lua, action="install")

    removed = survival_hook_operation(
        path, plan, lua_text=lua, action="remove",
    )
    assert removed["action"] == "remove"
    assert path.read_bytes() == original
    assert Path(removed["backup"]).read_bytes() != original

    with pytest.raises(ValueError, match="not installed"):
        survival_hook_operation(path, plan, lua_text=lua, action="remove")


def test_survival_hook_does_not_edit_unknown_script_or_stale_lua(
    tmp_path,
) -> None:
    from sm_atlas.ground_truth import render_ground_probe_lua

    path = tmp_path / "SurvivalGame.lua"
    plan = _plan()
    lua = render_ground_probe_lua(plan)
    path.write_text("this is not game script", encoding="utf-8")

    with pytest.raises(ValueError, match="does not look"):
        survival_hook_operation(path, plan, lua_text=lua, action="install")
    assert path.read_text(encoding="utf-8") == "this is not game script"

    path.write_bytes(_source())
    stale_plan = json.loads(json.dumps(plan))
    stale_plan["critical_edge"]["world_samples"][0]["world_xy"] = [
        45.5, -108.0,
    ]
    with pytest.raises(ValueError, match="Lua file differs"):
        survival_hook_operation(
            path, stale_plan, lua_text=lua, action="install",
        )
    assert path.read_bytes() == _source()


def test_survival_hook_refuses_remove_with_unrelated_trailing_changes(
    tmp_path,
) -> None:
    from sm_atlas.ground_truth import render_ground_probe_lua

    path = tmp_path / "SurvivalGame.lua"
    plan = _plan()
    lua = render_ground_probe_lua(plan)
    path.write_bytes(_source())
    survival_hook_operation(path, plan, lua_text=lua, action="install")
    path.write_bytes(path.read_bytes() + b"-- user additional update\n")
    snapshot = path.read_bytes()

    with pytest.raises(ValueError, match="content after"):
        survival_hook_operation(path, plan, lua_text=lua, action="remove")
    assert path.read_bytes() == snapshot


def test_survival_hook_cli_is_opt_in_and_parseable() -> None:
    from sm_atlas.cli import build_parser

    parser = build_parser()
    default = parser.parse_args([
        "tile-ground-survival", "ground_plan.json",
        r"F:\Steam\Survival\Scripts\game\SurvivalGame.lua",
        "--lua", "atlas_ground_probe.lua",
    ])
    assert default.install is False
    assert default.remove is False
    assert default.lua.name == "atlas_ground_probe.lua"

    install = parser.parse_args([
        "tile-ground-survival", "ground_plan.json", "SurvivalGame.lua",
        "--lua", "atlas_ground_probe.lua", "--install",
    ])
    assert install.install is True
    assert install.remove is False

    remove = parser.parse_args([
        "tile-ground-survival", "ground_plan.json", "SurvivalGame.lua",
        "--lua", "atlas_ground_probe.lua", "--remove",
    ])
    assert remove.remove is True


def test_hook_rejects_mismatched_file_name(tmp_path) -> None:
    from sm_atlas.ground_truth import render_ground_probe_lua

    path = tmp_path / "OtherGame.lua"
    path.write_bytes(_source())
    plan = _plan()
    with pytest.raises(ValueError, match="exact SurvivalGame"):
        survival_hook_operation(
            path, plan,
            lua_text=render_ground_probe_lua(plan),
        )
