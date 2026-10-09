from __future__ import annotations

import json
from math import hypot

import pytest

from sm_atlas.ground_expanded_grid import (
    _rotate_local_xy_displacement,
    prepare_expanded_ground_plan,
)
from sm_atlas.ground_truth import _validated_ground_plan, render_ground_probe_lua


def _synthetic_input(rotation=0, *, centre=(4.5, 35.5)):
    data = []
    old_world_samples = []
    for i, x_offset in enumerate((-0.5, 0.0, 0.5)):
        for j in range(5):
            x = centre[0] + x_offset
            y = centre[1] + (j - 2) * 0.25
            z = 81.9 + 0.1 * j
            dx, dy = _rotate_local_xy_displacement(
                x, y, rotation,
            )
            wx, wy = 44.0 + dx, -140.0 + dy
            data.append({
                "index": i * 5 + j,
                "local_xyz": [x, y, z - 60],
                "world_xy": [wx, wy],
                "world_hit_z": z,
            })
            old_world_samples.append({
                "world_xy": [wx, wy],
                "estimated_surface_world_z": z + 0.2,
                "fraction": j / 4,
                "lateral_offset_m": x_offset,
            })
    plan = {
        "world_id": 23, "node_id": 120,
        "alignment": {
            "status": "two_or_more_independent_tunnel_anchors"
        },
        "layout_rotation_quarter_turns": rotation,
        "tile_dimensions_m": [32, 48, 32],
        "world_bounds": {
            "min": [44, -140, 60],
            "max": [76, -92, 92],
        },
        "tile_uuid": "01234567-89ab-cdef-0123-456789abcdef",
        "critical_edge": {"world_samples": old_world_samples},
    }
    return plan, data


@pytest.mark.parametrize("rotation", [0, 1, 2, 3])
def test_new_grid_has_25_distinct_off_grid_positions_with_verified_rotation(
    monkeypatch, rotation,
):
    from sm_atlas import ground_expanded_grid as module
    plan, data = _synthetic_input(rotation)
    monkeypatch.setattr(
        module, "inspect_ground_density",
        lambda p, log, tile: {"samples": data},
    )
    new, metadata = prepare_expanded_ground_plan(
        plan, "existing game logs", "existing.tile"
    )
    _validated_ground_plan(new)
    assert new["world_id"] == plan["world_id"]
    assert new["tile_uuid"] == plan["tile_uuid"]
    assert new["critical_edge"] != plan["critical_edge"]
    assert len(plan["critical_edge"]["world_samples"]) == 15
    assert len(new["critical_edge"]["world_samples"]) == 25
    assert metadata["distinct_integer_xy_columns"] == 25
    assert metadata["distinct_half_shift_xy_columns"] == 25
    assert metadata["requires_new_game_measurements"] is True
    assert render_ground_probe_lua(new).count("predictedZ =") == 25

    anchor = data[0]
    ax, ay = anchor["local_xyz"][:2]
    awx, awy = anchor["world_xy"]
    old_xy = {tuple(row["world_xy"]) for row in data}
    planned_xy = set()
    for k, sample in enumerate(new["critical_edge"]["world_samples"]):
        i, j = divmod(k, 5)
        lx = 2.31 + i
        ly = 33.31 + j
        dx, dy = _rotate_local_xy_displacement(
            lx - ax, ly - ay, rotation
        )
        assert sample["world_xy"] == pytest.approx(
            [awx + dx, awy + dy], abs=1e-6
        )
        assert tuple(sample["world_xy"]) not in old_xy
        planned_xy.add(tuple(sample["world_xy"]))
        source = data[sample["source_game_hit_index"]]
        assert sample["estimated_surface_world_z"] == pytest.approx(
            source["world_hit_z"], abs=1e-6
        )
        distance = hypot(
            lx - source["local_xyz"][0],
            ly - source["local_xyz"][1],
        )
        assert sample["distance_from_verified_hit_m"] == pytest.approx(
            distance, abs=1e-6
        )
        assert sample["fraction"] == j / 4
        assert sample["lateral_offset_m"] == i - 2
    assert len(planned_xy) == 25


def test_new_grid_rejects_too_near_tile_boundary_and_smaller_grid_works(
    monkeypatch,
):
    from sm_atlas import ground_expanded_grid as module
    plan, data = _synthetic_input(0, centre=(2.5, 35.5))
    monkeypatch.setattr(
        module, "inspect_ground_density",
        lambda p, log, tile: {"samples": data},
    )
    with pytest.raises(ValueError, match="tile boundary"):
        prepare_expanded_ground_plan(plan, "", "tile.tile")
    small, metadata = prepare_expanded_ground_plan(
        plan, "", "tile.tile", grid_size=3
    )
    assert len(small["critical_edge"]["world_samples"]) == 9
    assert metadata["distinct_integer_xy_columns"] == 9


@pytest.mark.parametrize("bad", [0, 2, 4, 8, True, 5.0])
def test_grid_size_restrictions_refuse_unintended_density(
    monkeypatch, bad,
):
    plan, _ = _synthetic_input()
    with pytest.raises(ValueError, match="grid_size"):
        prepare_expanded_ground_plan(
            plan, "", "tile.tile", grid_size=bad
        )


def test_grid_refuses_invalid_old_anchors_and_insufficient_hits(monkeypatch):
    from sm_atlas import ground_expanded_grid as module
    plan, data = _synthetic_input()
    plan["alignment"]["status"] = "not_anchored"
    with pytest.raises(ValueError, match="two independent"):
        prepare_expanded_ground_plan(plan, "", "tile.tile")
    plan["alignment"]["status"] = "two_or_more_independent_tunnel_anchors"
    monkeypatch.setattr(
        module, "inspect_ground_density",
        lambda p, log, tile: {"samples": data[:3]},
    )
    with pytest.raises(ValueError, match="at least four"):
        prepare_expanded_ground_plan(plan, "", "tile.tile")


def test_cli_grid_plan_does_not_overwrite_original_plan_or_existing_output(
    monkeypatch, tmp_path, capsys,
):
    from sm_atlas import cli, ground_expanded_grid as module
    plan, data = _synthetic_input()
    monkeypatch.setattr(
        module, "inspect_ground_density",
        lambda p, log, tile: {"samples": data},
    )
    parser = cli.build_parser()
    args = parser.parse_args([
        "tile-ground-grid-plan", "old.json", "hits.log", "cave.tile",
        "--output", "new.json", "--size", "3",
    ])
    assert args.size == 3
    original = tmp_path / "old.json"
    logs = tmp_path / "hits.log"
    tile = tmp_path / "cave.tile"
    output = tmp_path / "new.json"
    original.write_text(json.dumps(plan), encoding="utf-8")
    logs.write_text("game logs", encoding="utf-8")
    tile.write_bytes(b"original tile untouched")
    assert cli.run_tile_ground_grid_plan(
        original, logs, tile, output, 3
    ) == 0
    new = json.loads(output.read_text(encoding="utf-8"))
    assert len(new["critical_edge"]["world_samples"]) == 9
    assert original.read_text(encoding="utf-8") == json.dumps(plan)
    assert tile.read_bytes() == b"original tile untouched"
    before = output.read_bytes()
    assert cli.run_tile_ground_grid_plan(
        original, logs, tile, output, 3
    ) == 1
    assert output.read_bytes() == before
    assert cli.run_tile_ground_grid_plan(
        original, logs, tile, original, 3
    ) == 1
    assert original.read_text(encoding="utf-8") == json.dumps(plan)
