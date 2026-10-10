"""Tests for safe run isolation and plan-aligned extraction from game logs."""
from __future__ import annotations

import json
import os

import pytest

from sm_atlas.ground_log_extract import (
    extract_ground_probe_run,
    extract_latest_ground_probe_from_directory,
)
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



def _write_game_log(folder, name, content, age):
    path = folder / name
    path.write_text(content, encoding="utf-8")
    os.utime(path, (age, age))
    return path


def test_directory_import_uses_newest_matching_probe_not_newest_file(tmp_path):
    plan = _plan()
    older = _write_game_log(
        tmp_path, "game-older.log", _run(plan, z_offset=0.1), 100,
    )
    chosen = _write_game_log(
        tmp_path, "game-measured.log", _run(plan, z_offset=0.8), 200,
    )
    _write_game_log(
        tmp_path, "game-other-world.log", _run(plan, world=12), 300,
    )
    _write_game_log(
        tmp_path, "game-unrelated.log", "[Lua] startup\n", 400,
    )
    _write_game_log(
        tmp_path, "something-else.log", _run(plan, z_offset=2.0), 500,
    )

    extracted, summary, source = extract_latest_ground_probe_from_directory(
        plan, tmp_path
    )
    assert source == chosen
    assert source != older
    assert summary["game_log_files_examined"] == 3
    assert summary["source_game_log"] == str(chosen)
    assert compare_ground_observations(plan, extracted)["samples"][0][
        "actual_z"
    ] == pytest.approx(82.3)


def test_directory_import_rejects_newer_matching_broken_run(tmp_path):
    plan = _plan()
    _write_game_log(
        tmp_path, "game-valid.log", _run(plan), 100,
    )
    _write_game_log(
        tmp_path, "game-truncated.log",
        _run(plan, indexes=[0, 1]), 200,
    )
    with pytest.raises(ValueError, match="newest matching probe.*2/3"):
        extract_latest_ground_probe_from_directory(plan, tmp_path)


def test_directory_import_rejects_newer_matching_wrong_coordinates(tmp_path):
    plan = _plan()
    _write_game_log(tmp_path, "game-valid.log", _run(plan), 100)
    altered = _run(plan).replace(
        "ATLAS_GROUND,0,1,44.310000",
        "ATLAS_GROUND,0,1,47.310000",
    )
    _write_game_log(tmp_path, "game-mismatched.log", altered, 200)
    with pytest.raises(ValueError, match="plan coordinates"):
        extract_latest_ground_probe_from_directory(plan, tmp_path)


def test_directory_import_explicitly_refuses_missing_or_unrelated_logs(
    tmp_path,
):
    plan = _plan()
    with pytest.raises(ValueError, match="no game.*log"):
        extract_latest_ground_probe_from_directory(plan, tmp_path)
    _write_game_log(
        tmp_path, "game-other.log", _run(plan, world=12), 100,
    )
    with pytest.raises(ValueError, match="no matching probe"):
        extract_latest_ground_probe_from_directory(plan, tmp_path)


def test_directory_import_never_descends_into_nested_logs_or_follows_symlinks(
    tmp_path,
):
    plan = _plan()
    subdir = tmp_path / "nested"
    subdir.mkdir()
    old = _write_game_log(subdir, "game-hidden.log", _run(plan), 100)
    with pytest.raises(ValueError, match="no game.*log"):
        extract_latest_ground_probe_from_directory(plan, tmp_path)
    try:
        (tmp_path / "game-linked.log").symlink_to(old)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not available")
    with pytest.raises(ValueError, match="no game.*log"):
        extract_latest_ground_probe_from_directory(plan, tmp_path)


def test_directory_import_preserves_ascii_probe_in_non_utf8_full_log(
    tmp_path,
):
    plan = _plan()
    source = tmp_path / "game-console.log"
    source.write_bytes(b"\xff unrelated game text\n" + _run(plan).encode())
    extracted, summary, selected = extract_latest_ground_probe_from_directory(
        plan, tmp_path,
    )
    assert selected == source
    assert summary["extracted_records"] == 3
    assert extracted.count("ATLAS_GROUND,") == 3


def test_cli_directory_mode_validates_inputs_and_preserves_originals(
    tmp_path, capsys,
):
    from sm_atlas.cli import build_parser, run_tile_ground_extract

    parser = build_parser()
    parsed = parser.parse_args([
        "tile-ground-extract", "plan.json",
        "--logs-dir", "Logs",
        "--output", "ground_hits.log",
    ])
    assert parsed.game_log is None
    assert parsed.logs_dir.name == "Logs"
    assert parsed.output.name == "ground_hits.log"

    logs = tmp_path / "Logs"
    logs.mkdir()
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(_plan()), encoding="utf-8")
    game_log = _write_game_log(logs, "game-20261010.log", _run(_plan()), 100)
    output = tmp_path / "validated.log"
    game_before, plan_before = game_log.read_bytes(), plan_file.read_bytes()

    assert run_tile_ground_extract(
        plan_file, None, output, logs_dir=logs,
    ) == 0
    assert output.read_text().count("ATLAS_GROUND,") == 3
    assert "source_game_log=" in capsys.readouterr().out
    assert run_tile_ground_extract(
        plan_file, None, output, logs_dir=logs,
    ) == 1
    assert run_tile_ground_extract(
        plan_file, None, game_log, logs_dir=logs,
    ) == 1
    assert run_tile_ground_extract(
        plan_file, game_log, tmp_path / "bad.log", logs_dir=logs,
    ) == 1
    assert run_tile_ground_extract(
        plan_file, None, tmp_path / "bad.log",
    ) == 1
    assert game_log.read_bytes() == game_before
    assert plan_file.read_bytes() == plan_before
