from __future__ import annotations

import pytest

from sm_atlas.ground_hypotheses import (
    _candidate_floor_crossings,
    compare_trilinear_hypotheses,
)


def _volume() -> tuple[bytearray, tuple[int, int, int]]:
    dims = (4, 4, 6)
    volume = bytearray([255]) * (dims[0] * dims[1] * dims[2])
    for x in range(dims[0]):
        for y in range(dims[1]):
            for z in range(dims[2]):
                volume[(x * dims[1] + y) * dims[2] + z] = (
                    0x0F if z <= 2 else 0x00
                )
    return volume, dims


def test_4bit_upward_crossing_and_not_5bit_for_same_raw_bytes():
    volume, dims = _volume()
    opts = dict(
        local_x=1.5, local_y=1.5, z_min=0.5, z_max=4.0,
        sample_shift_x=0.0, sample_shift_y=0.0,
        sample_shift_z=0.0,
    )
    roots4 = _candidate_floor_crossings(
        volume, dims, bits=4, **opts,
    )
    roots5 = _candidate_floor_crossings(
        volume, dims, bits=5, **opts,
    )
    assert roots4 == [pytest.approx(2 + 7 / 15, abs=1e-6)]
    assert roots5 == []


def test_3d_model_is_computed_from_interpolated_density_not_root_height():
    volume, dims = _volume()
    # A varying layer on the right side shifts a trilinear crossing.
    for y in (1, 2):
        volume[(2 * dims[1] + y) * dims[2] + 2] = 0x08
    roots = _candidate_floor_crossings(
        volume, dims, local_x=1.5, local_y=1.5,
        z_min=1.5, z_max=3.5, bits=4,
        sample_shift_x=0, sample_shift_y=0, sample_shift_z=0,
    )
    # Blended packed density at z=2 is 11.5 (15/2 + 8/2),
    # at z=3 is 0; isosurface is z=2+3.5/11.5.
    assert roots == [pytest.approx(2 + 3.5 / 11.5, abs=1e-6)]


def test_unknown_voxel_blocks_candidate_instead_of_inventing_value():
    volume, dims = _volume()
    volume[(2 * dims[1] + 1) * dims[2] + 2] = 255
    opts = dict(
        local_x=1.5, local_y=1.5, z_min=1.5, z_max=3.5,
        bits=4, sample_shift_x=0, sample_shift_y=0,
        sample_shift_z=0,
    )
    assert _candidate_floor_crossings(volume, dims, **opts) == []


def test_model_grid_runs_16_fixed_hypotheses_and_reports_coverage(monkeypatch):
    from sm_atlas import ground_hypotheses
    volume, dims = _volume()
    observed = round(2 + 7 / 15, 6)
    monkeypatch.setattr(
        ground_hypotheses, "inspect_ground_density",
        lambda plan, log, tile: {
            "world_id": 23,
            "hits": 1,
            "tile_path": str(tile),
            "samples": [{
                "index": 0,
                "world_hit_z": observed,
                "local_xyz": [1.5, 1.5, observed],
            }],
        },
    )
    monkeypatch.setattr(ground_hypotheses, "_dimensions", lambda path: dims)
    monkeypatch.setattr(
        ground_hypotheses, "_load_density_bytes",
        lambda path, dimensions: (volume, 0),
    )
    plan = {
        "world_bounds": {"min": [0, 0, 0]},
        "critical_edge": {"world_samples": [
            {"estimated_surface_world_z": 2.5},
        ]},
    }
    result = compare_trilinear_hypotheses(plan, "game log", "dummy.tile")
    assert result["models_evaluated"] == 16
    assert result["hits_from_game"] == 1
    best = result["models"][0]
    assert best["bits"] == 4
    assert best["single_candidates"] == 1
    assert best["rmse_m"] == pytest.approx(0, abs=1e-6)
    assert len(best["samples"]) == 1
    assert all(m["no_candidates"] == 1 for m in result["models"] if m["bits"] == 5)


def test_hypothesis_cli_parser_is_explicitly_read_only():
    from sm_atlas.cli import build_parser

    args = build_parser().parse_args([
        "tile-ground-hypotheses", "ground_plan.json",
        "atlas_ground_hits.log", "passage_2x3x2.tile", "--json",
    ])
    assert args.plan.name == "ground_plan.json"
    assert args.log.name == "atlas_ground_hits.log"
    assert args.tile.name == "passage_2x3x2.tile"
    assert args.json is True


def test_six_bit_candidate_crossing_is_opt_in_only():
    volume, dims = _volume()
    for x in range(dims[0]):
        for y in range(dims[1]):
            for z in range(dims[2]):
                volume[(x * dims[1] + y) * dims[2] + z] = (
                    0x3F if z <= 2 else 0x00
                )
    opts = dict(
        local_x=1.5, local_y=1.5, z_min=1.5, z_max=3.5,
        sample_shift_x=0, sample_shift_y=0, sample_shift_z=0,
    )
    roots = _candidate_floor_crossings(volume, dims, bits=6, **opts)
    assert roots == [pytest.approx(2 + 31 / 63, abs=1e-6)]
    with pytest.raises(ValueError, match="4, 5 or 6"):
        _candidate_floor_crossings(volume, dims, bits=7, **opts)


def test_six_bit_grid_opt_in_preserves_legacy_model_count(monkeypatch):
    from sm_atlas import ground_hypotheses
    volume, dims = _volume()
    for x in range(dims[0]):
        for y in range(dims[1]):
            for z in range(dims[2]):
                volume[(x * dims[1] + y) * dims[2] + z] = (
                    0x3F if z <= 2 else 0
                )
    hit_z = round(2 + 31 / 63, 6)
    monkeypatch.setattr(
        ground_hypotheses, "inspect_ground_density",
        lambda plan, log, tile: {
            "world_id": 23, "hits": 1, "tile_path": str(tile),
            "samples": [{
                "index": 0, "world_hit_z": hit_z,
                "local_xyz": [1.5, 1.5, hit_z],
            }],
        },
    )
    monkeypatch.setattr(ground_hypotheses, "_dimensions", lambda path: dims)
    monkeypatch.setattr(
        ground_hypotheses, "_load_density_bytes",
        lambda path, dims: (volume, 0),
    )
    plan = {
        "world_bounds": {"min": [0, 0, 0]},
        "critical_edge": {"world_samples": [
            {"estimated_surface_world_z": hit_z},
        ]},
    }
    legacy = compare_trilinear_hypotheses(plan, "log", "dummy.tile")
    extended = compare_trilinear_hypotheses(
        plan, "log", "dummy.tile", include_six_bit=True,
    )
    assert legacy["models_evaluated"] == 16
    assert all(model["bits"] in (4, 5) for model in legacy["models"])
    assert legacy["six_bit_hypothesis_opted_in"] is False
    assert extended["models_evaluated"] == 24
    assert len([m for m in extended["models"] if m["bits"] == 6]) == 8
    assert extended["six_bit_hypothesis_opted_in"] is True
    assert any(
        m["bits"] == 6 and m["single_candidates"] == 1
        for m in extended["models"]
    )


def test_six_bit_flags_parse_only_for_read_only_ground_commands():
    from sm_atlas.cli import build_parser
    parser = build_parser()
    for command in ("tile-ground-hypotheses", "tile-ground-slope-audit"):
        common = [command, "plan.json", "game.log", "sample.tile"]
        assert parser.parse_args(common).include_6_bit is False
        assert parser.parse_args(common + ["--include-6-bit"]).include_6_bit
