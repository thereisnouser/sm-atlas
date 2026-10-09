from __future__ import annotations

import json

import pytest

from sm_atlas.ground_truth import (
    compare_ground_observations,
    render_ground_probe_lua,
)


def _plan() -> dict:
    samples = []
    for lateral in (-0.5, 0.0, 0.5):
        for index in range(5):
            samples.append({
                "world_xy": [44.5 + lateral, -107.5 - index * 0.25],
                "estimated_surface_world_z": 82.0 + index * 0.3,
                "fraction": index / 4.0,
                "lateral_offset_m": lateral,
            })
    return {
        "world_id": 23,
        "alignment": {
            "status": "two_or_more_independent_tunnel_anchors",
            "distinct_sockets": 4,
            "distinct_tunnels": 4,
        },
        "critical_edge": {"world_samples": samples},
    }


def _record(plan: dict, index: int, actual_z: float | None,
            *, kind: str = "terrainSurface",
            world: int = 23) -> str:
    sample = plan["critical_edge"]["world_samples"][index]
    x, y = sample["world_xy"]
    predicted = sample["estimated_surface_world_z"]
    hit = actual_z is not None
    return (
        f"[game log] ATLAS_GROUND,{index},{int(hit)},"
        f"{x:.6f},{y:.6f},{predicted:.6f},"
        f"{world},{actual_z if hit else 0:.6f},"
        f"0.0,0.0,1.0,{kind if hit else 'miss'}"
    )


def test_generated_lua_references_real_world_userdata_and_logs_samples() -> None:
    generated = render_ground_probe_lua(_plan())
    assert "function smAtlasGroundProbe(world)" in generated
    assert "world.id ~= 23" in generated
    assert "sm.physics.filter.terrainSurface" in generated
    assert "sm.physics.filter.allTerrain" in generated
    assert "sm.physics.raycast(" in generated
    assert "ATLAS_GROUND_META,world=23,count=15" in generated
    assert '"ATLAS_GROUND,%d,%d' in generated
    assert generated.count("predictedZ =") == 15
    assert "-- NOT a working standalone mod" in generated


def test_comparison_tracks_measured_gradient_and_bias_separately() -> None:
    plan = _plan()
    # The centre track is at indexes 5..9. Observed slope 0.35/0.25=1.4.
    observations = "\n".join([
        _record(plan, 5, 82.2),
        _record(plan, 6, 82.55),
    ])
    result = compare_ground_observations(plan, observations)
    assert result["planned_points"] == 15
    assert result["logged_points"] == 2
    assert result["terrain_surface_hits"] == 2
    assert result["not_sampled"] == 13
    errors = result["measured_minus_predicted"]
    assert errors["median_offset_m"] == pytest.approx(0.225)
    assert errors["max_residual_after_median_offset_m"] == 0.025
    assert result["samples"][5]["status"] == "terrain_surface_hit"
    assert result["track_summaries"][0]["lateral_offset_m"] == 0.0
    assert result["track_summaries"][0]["max_observed_absolute_gradient"] == 1.4


def test_actual_voxel_terrain_raycast_series_is_measured_ground() -> None:
    """Regression for 15 raycast hits captured in Survival 1.0 (2026-10-08)."""
    plan = _plan()
    predicted_z = [82.1667, 82.4750, 82.7833, 83.0917, 83.4]
    for index, sample in enumerate(plan["critical_edge"]["world_samples"]):
        sample["estimated_surface_world_z"] = predicted_z[index % 5]
    observed_z = [
        81.785721, 81.801186, 81.816666, 81.843330, 81.870003,
        81.833336, 81.860001, 81.886673, 81.913338, 81.940002,
        81.890808, 81.917473, 81.944138, 81.994568, 82.045006,
    ]
    logs = "\n".join(
        _record(plan, i, z, kind="voxelTerrain")
        for i, z in enumerate(observed_z)
    )
    result = compare_ground_observations(plan, logs)
    assert result["logged_points"] == 15
    assert result["terrain_surface_hits"] == 15
    assert result["other_hits_or_misses"] == 0
    assert result["non_upward_terrain_surface_hits"] == 0
    assert result["not_sampled"] == 0
    assert all(
        row["status"] == "terrain_surface_hit"
        for row in result["samples"]
    )
    assert len(result["track_summaries"]) == 3
    assert all(
        track["adjacent_measured_segments"] == 4
        for track in result["track_summaries"]
    )
    assert result["measured_minus_predicted"]["median_offset_m"] is not None
    assert result["track_summaries"][1]["max_observed_absolute_gradient"] == (
        pytest.approx(0.106688, abs=1e-6)
    )


def test_voxel_terrain_requires_upward_normal() -> None:
    plan = _plan()
    downward = _record(plan, 5, 82.0, kind="voxelTerrain").replace(
        ",0.0,0.0,1.0,voxelTerrain",
        ",0.0,0.0,-1.0,voxelTerrain",
    )
    result = compare_ground_observations(plan, downward)
    assert result["terrain_surface_hits"] == 0
    assert result["non_upward_terrain_surface_hits"] == 1
    assert result["samples"][5]["status"] == (
        "non_upward_terrain_surface_hit"
    )


def test_unknown_physics_hit_is_not_silently_treated_as_ground() -> None:
    plan = _plan()
    unknown = _record(plan, 0, 82.0, kind="body")
    result = compare_ground_observations(plan, unknown)
    assert result["terrain_surface_hits"] == 0
    assert result["other_hits_or_misses"] == 1
    assert result["samples"][0]["hit_type"] == "body"


def test_comparison_does_not_treat_assets_or_misses_as_ground() -> None:
    plan = _plan()
    observations = "\n".join([
        _record(plan, 0, 82.2, kind="terrainAsset"),
        _record(plan, 1, None),
    ])
    result = compare_ground_observations(plan, observations)
    assert result["terrain_surface_hits"] == 0
    assert result["other_hits_or_misses"] == 2
    assert result["samples"][0]["status"] == "other_collision_type"
    assert result["samples"][1]["status"] == "no_hit"
    assert result["measured_minus_predicted"]["median_offset_m"] is None


def test_downward_terrain_normal_is_not_accepted_as_floor() -> None:
    plan = _plan()
    ceiling = _record(plan, 5, 85.0).replace(
        ",0.0,0.0,1.0,terrainSurface",
        ",0.0,0.0,-1.0,terrainSurface",
    )
    result = compare_ground_observations(plan, ceiling)
    assert result["terrain_surface_hits"] == 0
    assert result["non_upward_terrain_surface_hits"] == 1
    assert result["other_hits_or_misses"] == 1
    assert result["samples"][5]["status"] == (
        "non_upward_terrain_surface_hit"
    )
    assert result["track_summaries"] == []


def test_comparison_rejects_wrong_world_duplicate_and_stale_plan() -> None:
    plan = _plan()
    line = _record(plan, 0, 82.0)
    with pytest.raises(ValueError, match="duplicate"):
        compare_ground_observations(plan, line + "\n" + line)
    with pytest.raises(ValueError, match="does not match"):
        compare_ground_observations(plan, _record(plan, 0, 82, world=12))

    stale = json.loads(json.dumps(plan))
    stale["critical_edge"]["world_samples"][0]["world_xy"][0] += 5.0
    with pytest.raises(ValueError, match="plan coordinates"):
        compare_ground_observations(stale, line)


def test_no_log_records_and_bad_columns_are_rejected() -> None:
    with pytest.raises(ValueError, match="no ATLAS_GROUND"):
        compare_ground_observations(_plan(), "No raycast output")
    with pytest.raises(ValueError, match="12 comma-separated"):
        compare_ground_observations(
            _plan(), "ATLAS_GROUND,1,0,incorrect",
        )


def test_lua_refuses_unanchored_or_nonfinite_plans() -> None:
    plan = _plan()
    plan["alignment"]["status"] = "insufficient_independent_tunnel_anchors"
    with pytest.raises(ValueError, match="two independent"):
        render_ground_probe_lua(plan)

    plan = _plan()
    plan["critical_edge"]["world_samples"][0]["world_xy"][0] = float("nan")
    with pytest.raises(ValueError, match="invalid world sample"):
        render_ground_probe_lua(plan)

    plan = _plan()
    plan["critical_edge"]["world_samples"][1] = (
        plan["critical_edge"]["world_samples"][0].copy()
    )
    with pytest.raises(ValueError, match="duplicate XY"):
        render_ground_probe_lua(plan)


def test_tile_ground_commands_have_explicit_file_paths() -> None:
    from sm_atlas.cli import build_parser

    parser = build_parser()
    lua_args = parser.parse_args([
        "tile-ground-lua", "plan.json", "--output", "atlas.lua",
    ])
    assert lua_args.plan.name == "plan.json"
    assert lua_args.output.name == "atlas.lua"

    compare_args = parser.parse_args([
        "tile-ground-compare", "plan.json", "game.log", "--json",
    ])
    assert compare_args.log.name == "game.log"
    assert compare_args.json


def test_tile_world_probe_utf8_json_output_parser_and_guard() -> None:
    from sm_atlas.cli import build_parser, run_tile_world_probe

    parser = build_parser()
    args = parser.parse_args([
        "tile-world-probe", "save.db", "tile.tile",
        "--world", "23", "--node", "322", "--json",
        "--output", "ground_plan.json",
    ])
    assert args.output.name == "ground_plan.json"
    # Reject output without JSON before trying to open either input file.
    assert run_tile_world_probe(
        args.save, args.tile, args.world, args.node,
        None, args.density_bits, args.match_tolerance,
        False, args.output,
    ) == 1


def test_no_gap_bridging_when_a_raycast_sample_is_missing() -> None:
    plan = _plan()
    # Centre track indexes 5 and 7 are separated by one missing point.
    result = compare_ground_observations(
        plan, "\n".join([
            _record(plan, 5, 82.0),
            _record(plan, 7, 82.8),
        ]),
    )
    assert result["track_summaries"][0]["adjacent_measured_segments"] == 0
    assert result["track_summaries"][0]["max_observed_absolute_gradient"] is None


@pytest.mark.parametrize("points_per_lane", [3, 5, 7])
def test_ground_comparison_accepts_actual_planned_track_spacing(points_per_lane):
    plan = _plan()
    plan["critical_edge"]["world_samples"] = [
        {
            "world_xy": [44.5, -107.0 - i],
            "estimated_surface_world_z": 82.0,
            "fraction": i / (points_per_lane - 1),
            "lateral_offset_m": 0.0,
        }
        for i in range(points_per_lane)
    ]
    log = "\n".join(
        _record(plan, i, 82.0 + i * 0.2, kind="voxelTerrain")
        for i in range(points_per_lane)
    )
    result = compare_ground_observations(plan, log)
    track = result["track_summaries"][0]
    assert track["adjacent_measured_segments"] == points_per_lane - 1
    assert track["max_observed_absolute_gradient"] == pytest.approx(0.2)


@pytest.mark.parametrize("points_per_lane", [3, 5, 7])
def test_ground_comparison_never_bridges_missing_planned_middle(points_per_lane):
    plan = _plan()
    plan["critical_edge"]["world_samples"] = [
        {
            "world_xy": [44.5, -107.0 - i],
            "estimated_surface_world_z": 82.0,
            "fraction": i / (points_per_lane - 1),
            "lateral_offset_m": 0.0,
        }
        for i in range(points_per_lane)
    ]
    missing_index = points_per_lane // 2
    log = "\n".join(
        _record(plan, i, 82.0 + i * 0.2, kind="voxelTerrain")
        for i in range(points_per_lane) if i != missing_index
    )
    track = compare_ground_observations(plan, log)["track_summaries"][0]
    assert track["adjacent_measured_segments"] == max(0, points_per_lane - 3)
    assert all(
        missing_index not in (step["from_index"], step["to_index"])
        for step in track["measured_segments"]
    )
