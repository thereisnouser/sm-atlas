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
        lambda path, dimensions, *, return_written=False: (
            (volume, 0, bytearray([1]) * len(volume))
            if return_written else (volume, 0)
        ),
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
        lambda path, dims, *, return_written=False: (
            (volume, 0, bytearray([1]) * len(volume))
            if return_written else (volume, 0)
        ),
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


def test_explicit_written_ff_can_create_six_bit_candidate_crossing():
    from sm_atlas.ground_hypotheses import _interpolated_layer
    dims = (2, 2, 3)
    volume = bytearray([0] * (dims[0] * dims[1] * dims[2]))
    written = bytearray([1] * len(volume))
    for x in range(2):
        for y in range(2):
            volume[(x * 2 + y) * 3] = 0xFF
    opts = dict(
        local_x=0.5, local_y=0.5, z_min=0.0, z_max=2.0,
        bits=6, sample_shift_x=0.0, sample_shift_y=0.0,
        sample_shift_z=0.0,
    )
    # FF is 63 density under this deliberately unverified six-bit mask.
    assert _interpolated_layer(
        volume, dims, 0.5, 0.5, 0, 0x3F, written
    ) == 63
    # Legacy unknown/FF conflation finds no crossing.
    assert _candidate_floor_crossings(volume, dims, **opts) == []
    assert _candidate_floor_crossings(
        volume, dims, written=written, **opts
    ) == [pytest.approx(31 / 63, abs=1e-6)]
    written[0] = 0
    # A truly missing interpolation neighbour must fail closed.
    assert _candidate_floor_crossings(
        volume, dims, written=written, **opts
    ) == []


def test_ff_does_not_break_written_mask_for_four_or_five_bits():
    dims = (2, 2, 3)
    volume = bytearray([0] * 12)
    written = bytearray([1] * 12)
    for x in range(2):
        for y in range(2):
            volume[(x * 2 + y) * 3] = 255
    opts = dict(
        local_x=0.5, local_y=0.5, z_min=0, z_max=2,
        sample_shift_x=0, sample_shift_y=0, sample_shift_z=0,
        written=written,
    )
    for bits, top in ((4, 15), (5, 31)):
        # Each hypothesis uses only its own low bits; no FF is dropped.
        result = _candidate_floor_crossings(volume, dims, bits=bits, **opts)
        assert result == [pytest.approx((top - (1 << (bits - 1))) / top)]


def test_ff_sensitivity_reports_changed_ground_candidates(monkeypatch):
    from sm_atlas import ground_hypotheses
    volume, dims = _volume()
    for x in range(dims[0]):
        for y in range(dims[1]):
            for z in range(dims[2]):
                volume[(x * dims[1] + y) * dims[2] + z] = (
                    255 if z <= 2 else 0
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
        lambda path, dims, *, return_written=False: (
            (volume, 0, bytearray([1]) * len(volume))
            if return_written else (volume, 0)
        ),
    )
    plan = {
        "world_bounds": {"min": [0, 0, 0]},
        "critical_edge": {"world_samples": [
            {"estimated_surface_world_z": hit_z},
        ]},
    }
    report = compare_trilinear_hypotheses(
        plan, "log", "tile.tile", include_six_bit=True,
    )
    assert report["written_ff_voxels_in_tile"] == 4 * 4 * 3
    model = next(m for m in report["models"] if (
        m["bits"] == 6 and m["lattice_origin_shift_xyz"] == [0, 0, 0]
    ))
    assert model["single_candidates"] == 1
    assert model["ff_sensitive_samples"] == 1
    assert model["samples"][0]["candidate_world_z"] == [hit_z]

def _fixed_lane_model(bits, errors):
    samples = []
    for i, error in enumerate(errors):
        samples.append({
            "index": i, "status": (
                "single_candidate" if error is not None else "no_candidate"
            ),
            "observed_world_z": 10.0,
            "candidate_world_z": (
                [10.0 + error] if error is not None else []
            ),
        })
    return {
        "bits": bits,
        "lattice_origin_shift_xyz": [0, 0, 0],
        "samples": samples,
    }


def test_lane_holdout_does_not_select_on_hidden_track_or_fit_its_bias():
    from sm_atlas.ground_hypotheses import _leave_one_track_out_diagnostic
    plan = [{"lateral_offset_m": lane} for lane in (-0.5, 0, 0.5)]
    # In the +0.5 lane, the training-perfect candidate is terrible.
    # The globally better hypothesis must not be selected by peeking.
    a = _fixed_lane_model(4, [0, 0, 10])
    b = _fixed_lane_model(5, [1, 1, 0])
    result = _leave_one_track_out_diagnostic([a, b], plan)
    assert result["status"] == "within_site_diagnostic_only"
    fold = result["folds"][2]
    assert fold["held_out_lateral_offset_m"] == 0.5
    assert fold["chosen_bits"] == 4
    assert fold["training_unambiguous"] == 2
    assert fold["training_median_bias_m"] == 0
    assert fold["held_out_rmse_after_training_bias_m"] == 10
    assert fold["held_out_rmse_m"] == 10


def test_lane_holdout_reports_missing_roots_and_training_only_offset():
    from sm_atlas.ground_hypotheses import _leave_one_track_out_diagnostic
    plan = [{"lateral_offset_m": v} for v in (-1, 0, 1)]
    a = _fixed_lane_model(4, [2, 2, None])
    result = _leave_one_track_out_diagnostic([a], plan)
    assert result["status"] == "incomplete_within_site_diagnostic"
    last = result["folds"][2]
    assert last["training_median_bias_m"] == 2
    assert last["held_out_unambiguous"] == 0
    assert last["held_out_missing_or_ambiguous"] == 1
    assert last["held_out_rmse_after_training_bias_m"] is None
    assert result["folds"][0]["held_out_rmse_after_training_bias_m"] == 0


def test_lane_holdout_fails_closed_without_independent_lane_metadata():
    from sm_atlas.ground_hypotheses import _leave_one_track_out_diagnostic
    model = _fixed_lane_model(4, [0, 0, 0])
    assert _leave_one_track_out_diagnostic(
        [model], [{"lateral_offset_m": 0}] * 3
    )["status"] == "insufficient_distinct_tracks"
    assert _leave_one_track_out_diagnostic(
        [model], [{"lateral_offset_m": None}] * 3
    )["status"] == "unavailable_track_metadata"
    with pytest.raises(ValueError, match="indices"):
        _leave_one_track_out_diagnostic(
            [{**model, "samples": [{**model["samples"][0], "index": 9},
                                   *model["samples"][1:]]}],
            [{"lateral_offset_m": i} for i in range(3)],
        )


def test_lane_holdout_tracks_missing_game_hits_separately_from_model_failures():
    from sm_atlas.ground_hypotheses import _leave_one_track_out_diagnostic
    planned = [{"lateral_offset_m": lane}
               for lane in (-1, -1, 0, 0, 1, 1)]
    # Probe #3 was never an upward terrain hit, so its row is missing.
    # Probe #5 had a valid game hit, but the model has no unique root.
    complete = _fixed_lane_model(4, [0, 0, 0, 0, 0, None])
    sparse = {**complete, "samples": [
        row for row in complete["samples"] if row["index"] != 3
    ]}
    result = _leave_one_track_out_diagnostic([sparse], planned)
    assert result["status"] == "incomplete_within_site_diagnostic"
    assert result["planned_samples"] == 6
    assert result["observed_game_hits"] == 5
    assert result["missing_game_observations"] == 1
    middle = result["folds"][1]
    assert middle["held_out_game_hits"] == 1
    assert middle["held_out_missing_game_observations"] == 1
    assert middle["held_out_unambiguous"] == 1
    assert middle["held_out_missing_or_ambiguous"] == 0
    last = result["folds"][2]
    assert last["held_out_game_hits"] == 2
    assert last["held_out_missing_game_observations"] == 0
    assert last["held_out_unambiguous"] == 1
    assert last["held_out_missing_or_ambiguous"] == 1
    assert last["held_out_flat_baseline_rmse_on_scored_m"] == 0


def test_flat_baseline_fits_training_heights_only_on_same_scored_holdout():
    from sm_atlas.ground_hypotheses import _leave_one_track_out_diagnostic
    model = _fixed_lane_model(4, [0, 0, 0])
    model["samples"][2]["observed_world_z"] = 20.0
    model["samples"][2]["candidate_world_z"] = [20.0]
    result = _leave_one_track_out_diagnostic(
        [model], [{"lateral_offset_m": x} for x in (-1, 0, 1)],
    )
    held = result["folds"][2]
    assert held["training_median_bias_m"] == 0
    assert held["held_out_rmse_after_training_bias_m"] == 0
    assert held["held_out_flat_baseline_rmse_on_scored_m"] == 10
    assert held["held_out_rmse_gain_over_flat_baseline_m"] == 10


def test_sparse_measurements_integrate_into_fixed_candidate_pipeline(monkeypatch):
    from sm_atlas import ground_hypotheses
    volume, dims = _volume()
    monkeypatch.setattr(
        ground_hypotheses, "inspect_ground_density",
        lambda plan, log, tile: {
            "world_id": 23, "hits": 2, "tile_path": str(tile),
            "samples": [
                {"index": 0, "world_hit_z": 2.5,
                 "local_xyz": [1.5, 1.5, 2.5]},
                {"index": 2, "world_hit_z": 2.5,
                 "local_xyz": [1.5, 1.5, 2.5]},
            ],
        },
    )
    monkeypatch.setattr(ground_hypotheses, "_dimensions", lambda tile: dims)
    monkeypatch.setattr(
        ground_hypotheses, "_load_density_bytes",
        lambda tile, dimensions, *, return_written=False: (
            (volume, 0, bytearray([1]) * len(volume))
            if return_written else (volume, 0)
        ),
    )
    plan = {
        "world_bounds": {"min": [0, 0, 0]},
        "critical_edge": {"world_samples": [
            {"estimated_surface_world_z": 2.5, "lateral_offset_m": lane}
            for lane in (-0.5, 0.0, 0.5)
        ]},
    }
    result = ground_hypotheses.compare_trilinear_hypotheses(
        plan, "log", "dummy.tile"
    )
    holdout = result["cross_track_holdout"]
    assert holdout["planned_samples"] == 3
    assert holdout["observed_game_hits"] == 2
    assert holdout["missing_game_observations"] == 1
    assert holdout["status"] == "incomplete_within_site_diagnostic"


def test_lane_holdout_rejects_repeated_and_inconsistent_source_indexes():
    from sm_atlas.ground_hypotheses import _leave_one_track_out_diagnostic
    planned = [{"lateral_offset_m": i} for i in range(3)]
    a = _fixed_lane_model(4, [0, 0, 0])
    duplicate = {**a, "samples": a["samples"] + [a["samples"][1]]}
    with pytest.raises(ValueError, match="duplicate"):
        _leave_one_track_out_diagnostic([duplicate], planned)
    b = _fixed_lane_model(5, [0, 0, 0])
    b["samples"][1]["observed_world_z"] = 12
    with pytest.raises(ValueError, match="observed"):
        _leave_one_track_out_diagnostic([a, b], planned)
    b = _fixed_lane_model(5, [0, 0, 0])
    b["samples"] = b["samples"][:-1]
    with pytest.raises(ValueError, match="differ"):
        _leave_one_track_out_diagnostic([a, b], planned)
