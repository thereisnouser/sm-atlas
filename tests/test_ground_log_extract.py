"""Tests for safe run isolation and plan-aligned extraction from game logs."""
from __future__ import annotations

import json

import pytest

from sm_atlas.ground_log_extract import extract_ground_probe_run
from sm_atlas.ground_truth import compare_ground_observations


def _plan(size=3):
    return {
        "world_id": 23,
        "alignment": {
            "status": "two_or_more_independent_tunnel_anchors",
        },
        "critical_edge": {
            "world_samples": [
                {
                    "world_xy": [44.31, -107.31 - i],
                    "estimated_surface_world_z": 81.5 + 0.1 * i,
                    "fraction": i / (size - 1),
                    "lateral_offset_m": 0.0,
                }
                for i in range(size)
            ],
        },
    }


def _record(plan, index, *, measured_z=None, kind="voxelTerrain",
            world=23, x_shift=0.0, observed=True):
    sample = plan["critical_edge"]["world_samples"][index]
    x, y = sample["world_xy"]
    predicted = sample["estimated_surface_world_z"]
    z = predicted + 0.2 if measured_z is None else measured_z
    return (
        f"[2026-10-09] [Lua] ATLAS_GROUND,{index},{int(observed)},"
        f"{x + x_shift:.6f},{y:.6f},{predicted:.6f},"
        f"{world},{z:.6f},0,0,1,{kind if observed else 'miss'}"
    )


def _run(plan, *, z_offset=0.0, count=None, world=23,
         indexes=None):
    size = len(plan["critical_edge"]["world_samples"])
    lines = [
        f"[Lua] ATLAS_GROUND_META,world={world},"
        f"count={size if count is None else count}",
    ]
    for i in range(size) if indexes is None else indexes:
        lines.append(_record(
            plan, i, world=world,
            measured_z=plan["critical_edge"]["world_samples"][i][
                "estimated_surface_world_z"
            ] + z_offset,
        ))
    return "\n".join(lines)


@pytest.mark.parametrize("size", [9, 15, 25, 49])
def test_full_raw_log_extracts_all_plan_matched_points(size):
    plan = _plan(size)
    raw = (
        "[Lua] game boot\n"
        + _run(plan, z_offset=0.4)
        + "\n[Lua] game shutdown\n"
    )
    extracted, summary = extract_ground_probe_run(plan, raw)
    assert len(extracted.splitlines()) == size
    assert extracted.startswith("ATLAS_GROUND,0,")
    assert summary["expected_points"] == size
    assert summary["extracted_records"] == size
    assert summary["game_ground_hits"] == size
    assert summary["matching_runs_found"] == 1
    verified = compare_ground_observations(plan, extracted)
    assert verified["logged_points"] == size
    assert verified["not_sampled"] == 0


def test_latest_matching_run_is_selected_without_mixing_earlier_runs():
    plan = _plan()
    first = _run(plan, z_offset=0.1)
    later = _run(plan, z_offset=0.8)
    raw = first + "\n[LUA] unrelated debug message\n" + later
    extracted, summary = extract_ground_probe_run(plan, raw)
    assert summary["matching_runs_found"] == 2
    assert summary["total_probe_markers_found"] == 2
    verified = compare_ground_observations(plan, extracted)
    assert verified["samples"][0]["actual_z"] == pytest.approx(82.3)


def test_other_world_and_other_probe_count_are_not_mixed():
    plan = _plan()
    raw = (
        _run(plan, z_offset=0.5)
        + "\n" + _run(plan, world=12)
        + "\n" + _run(plan, count=25)
    )
    extracted, summary = extract_ground_probe_run(plan, raw)
    assert summary["matching_runs_found"] == 1
    assert summary["total_probe_markers_found"] == 3
    assert compare_ground_observations(plan, extracted)[
        "terrain_surface_hits"
    ] == 3


def test_last_matching_truncated_run_refuses_stale_fallback():
    plan = _plan()
    raw = _run(plan) + "\n" + _run(plan, indexes=[0, 1])
    with pytest.raises(ValueError, match="newest matching probe.*2/3"):
        extract_ground_probe_run(plan, raw)


def test_duplicate_or_wrong_point_in_latest_run_is_rejected():
    plan = _plan()
    duplicates = _run(plan, indexes=[0, 0, 1])
    with pytest.raises(ValueError, match="duplicate"):
        extract_ground_probe_run(plan, duplicates)
    actual_z = plan["critical_edge"]["world_samples"][1][
        "estimated_surface_world_z"
    ]
    wrong_position = _run(plan).replace(
        _record(plan, 1, measured_z=actual_z),
        _record(plan, 1, measured_z=actual_z, x_shift=0.5),
    )
    with pytest.raises(ValueError, match="plan coordinates"):
        extract_ground_probe_run(plan, wrong_position)


def test_missing_metadata_or_incompatible_plan_fails_closed():
    plan = _plan()
    with pytest.raises(ValueError, match="no ATLAS_GROUND_META"):
        extract_ground_probe_run(
            plan, "\n".join(_record(plan, i) for i in range(3))
        )
    with pytest.raises(ValueError, match="no probe marker matches"):
        extract_ground_probe_run(plan, _run(plan, count=25))
    with pytest.raises(ValueError, match="invalid ATLAS_GROUND_META"):
        extract_ground_probe_run(
            plan, "[Lua] ATLAS_GROUND_META,world=23,count=oops\n"
        )


def test_complete_run_with_misses_and_assets_is_valid_but_not_false_ground():
    plan = _plan()
    lines = [
        "[Lua] ATLAS_GROUND_META,world=23,count=3",
        _record(plan, 0, observed=False),
        _record(plan, 1, kind="terrainAsset"),
        _record(plan, 2),
    ]
    extracted, summary = extract_ground_probe_run(plan, "\n".join(lines))
    assert summary["game_ground_hits"] == 1
    assert summary["other_hits_or_misses"] == 2
    assert compare_ground_observations(plan, extracted)["not_sampled"] == 0


def test_cli_command_is_read_only_and_never_overwrites(tmp_path):
    from sm_atlas.cli import build_parser, run_tile_ground_extract

    args = build_parser().parse_args([
        "tile-ground-extract", "plan.json", "game.log",
        "--output", "isolated.log",
    ])
    assert args.output.name == "isolated.log"
    assert args.game_log.name == "game.log"

    plan_file = tmp_path / "plan.json"
    raw_file = tmp_path / "game.log"
    output = tmp_path / "isolated.log"
    plan_file.write_text(json.dumps(_plan()), encoding="utf-8")
    raw_file.write_text(_run(_plan()), encoding="utf-8")
    initial_plan = plan_file.read_bytes()
    initial_raw = raw_file.read_bytes()

    assert run_tile_ground_extract(plan_file, raw_file, output) == 0
    first = output.read_bytes()
    assert first.startswith(b"ATLAS_GROUND,0,")
    assert run_tile_ground_extract(plan_file, raw_file, output) == 1
    assert output.read_bytes() == first
    assert run_tile_ground_extract(plan_file, raw_file, raw_file) == 1
    assert plan_file.read_bytes() == initial_plan
    assert raw_file.read_bytes() == initial_raw
