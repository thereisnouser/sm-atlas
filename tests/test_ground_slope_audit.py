from __future__ import annotations

import pytest

from sm_atlas.ground_slope_audit import audit_ground_slopes


def _rows():
    rows = []
    for lateral, x, z_values in (
        (-0.5, 44.0, (81.785721, 81.801186, 81.816666, 81.843330, 81.870003)),
        (0.0, 44.5, (81.833336, 81.860001, 81.886673, 81.913338, 81.940002)),
        (0.5, 45.0, (81.890808, 81.917473, 81.944138, 81.994568, 82.045006)),
    ):
        for i, z in enumerate(z_values):
            rows.append({
                "index": len(rows),
                "lateral_offset_m": lateral,
                "fraction": i / 4,
                "status": "terrain_surface_hit",
                "world_xy": (x, -107.5 - i * 0.25),
                "actual_z": z,
                # Representative upward normal from real game logs.
                "normal_world": (-0.113549, 0.105379, 0.987928),
            })
    return rows


def test_audit_computes_actual_directional_grade_and_normal_agreement(
    monkeypatch,
):
    from sm_atlas import ground_slope_audit as module
    rows = _rows()
    monkeypatch.setattr(
        module, "compare_ground_observations",
        lambda plan, log: {
            "world_id": 23, "terrain_surface_hits": len(rows),
            "samples": rows,
        },
    )
    model_samples = [
        {
            "index": r["index"],
            "status": "single_candidate",
            "candidate_world_z": [r["actual_z"] + 0.5],
        }
        for r in rows
    ]
    bad_samples = [
        {
            "index": r["index"],
            "status": "single_candidate",
            "candidate_world_z": [r["actual_z"] + i / 4.0],
        }
        for i, r in enumerate(rows)
    ]
    monkeypatch.setattr(
        module, "compare_trilinear_hypotheses",
        lambda plan, log, tile: {
            "models": [
                {
                    "bits": 5,
                    "lattice_origin_shift_xyz": [0, 0, 0],
                    "single_candidates": 15, "rmse_m": 1.0,
                    "samples": bad_samples,
                },
                {
                    "bits": 4,
                    "lattice_origin_shift_xyz": [0, 0, 0.5],
                    "single_candidates": 15, "rmse_m": 0.5,
                    "samples": model_samples,
                },
            ],
        },
    )
    result = audit_ground_slopes({}, "", "dummy.tile")
    assert result["measured_hits"] == 15
    assert result["models_evaluated"] == 2
    assert len(result["lanes"]) == 3
    assert result["lanes"][1]["observed_end_to_end_rise_m"] == pytest.approx(
        0.106666, abs=1e-6
    )
    assert len(result["lanes"][1]["adjacent_normal_checks"]) == 4
    assert result["lanes"][1]["adjacent_normal_checks"][1][
        "observed_directional_grade"
    ] == pytest.approx(0.106688, abs=1e-6)
    assert result["lanes"][1]["adjacent_normal_checks"][1][
        "normal_implied_directional_grade"
    ] == pytest.approx(0.106667, abs=1e-5)
    # Wrong height bias alone should not impact the shape score.
    assert result["models_ranked_by_rise_error"][0]["bits"] == 4
    assert result["models_ranked_by_rise_error"][0][
        "mean_absolute_rise_error_m"
    ] == 0
    assert result["models_ranked_by_rise_error"][1][
        "mean_absolute_rise_error_m"
    ] == 1.0
    # All 12 quarter-metre segments are available with unambiguous roots.
    by_grade = result["models_ranked_by_local_grade_error"]
    assert by_grade[0]["bits"] == 4
    assert by_grade[0]["segments_scored"] == 12
    assert by_grade[0]["measured_segments"] == 12
    assert by_grade[0]["mean_absolute_local_grade_error"] == 0
    assert by_grade[1]["mean_absolute_local_grade_error"] == 1.0
    assert by_grade[0]["mean_absolute_normal_grade_error"] is not None
    # Three transverse tracks form a 3x5 grid, not just 12 Y edges.
    assert result["measured_cross_track_segments"] == 10
    by_patch = result["models_ranked_by_patch_grade_error"]
    assert by_patch[0]["patch_segments_scored"] == 22
    assert by_patch[0]["measured_patch_segments"] == 22
    assert by_patch[0]["mean_absolute_patch_grade_error"] == 0


def test_slope_audit_does_not_invent_missing_model_endpoint(monkeypatch):
    from sm_atlas import ground_slope_audit as module
    rows = _rows()
    monkeypatch.setattr(
        module, "compare_ground_observations",
        lambda plan, log: {
            "world_id": 23, "terrain_surface_hits": len(rows), "samples": rows,
        },
    )
    model = [
        {
            "index": r["index"], "status": "no_candidate",
            "candidate_world_z": [],
        }
        for r in rows
    ]
    monkeypatch.setattr(
        module, "compare_trilinear_hypotheses",
        lambda plan, log, tile: {
            "models": [{
                "bits": 4,
                "lattice_origin_shift_xyz": [0, 0, 0],
                "single_candidates": 0, "rmse_m": None,
                "samples": model,
            }],
        },
    )
    result = audit_ground_slopes({}, "", "dummy.tile")
    assert result["models_ranked_by_rise_error"][0]["lanes_scored"] == 0
    assert result["models_ranked_by_rise_error"][0][
        "mean_absolute_rise_error_m"
    ] is None


def test_slope_audit_cli_parser_is_read_only():
    from sm_atlas.cli import build_parser
    args = build_parser().parse_args([
        "tile-ground-slope-audit", "ground_plan.json",
        "atlas_ground_hits.log", "tunnel_2x3x2.tile", "--json",
    ])
    assert args.plan.name == "ground_plan.json"
    assert args.log.name == "atlas_ground_hits.log"
    assert args.tile.name == "tunnel_2x3x2.tile"
    assert args.json is True


def test_adjacent_grade_discriminates_internal_wiggles_with_same_end_rise(
    monkeypatch,
):
    from sm_atlas import ground_slope_audit as module
    rows = _rows()
    monkeypatch.setattr(
        module, "compare_ground_observations",
        lambda plan, log: {
            "world_id": 23, "terrain_surface_hits": len(rows), "samples": rows,
        },
    )
    # Both hypotheses exactly match each lane's net rise. The jagged
    # hypothesis only matches the endpoints, not the interior geometry.
    wiggle = (0.0, 0.2, 0.0, -0.2, 0.0)
    smooth = [
        {"index": r["index"], "status": "single_candidate",
         "candidate_world_z": [r["actual_z"] + 0.5]}
        for r in rows
    ]
    jagged = [
        {"index": r["index"], "status": "single_candidate",
         "candidate_world_z": [r["actual_z"] + wiggle[i % 5]]}
        for i, r in enumerate(rows)
    ]
    monkeypatch.setattr(
        module, "compare_trilinear_hypotheses",
        lambda plan, log, tile: {"models": [
            {"bits": 4, "lattice_origin_shift_xyz": [0, 0, 0],
             "single_candidates": 15, "rmse_m": 0.15,
             "samples": jagged},
            {"bits": 5, "lattice_origin_shift_xyz": [0, 0, 0],
             "single_candidates": 15, "rmse_m": 0.5,
             "samples": smooth},
        ]},
    )
    result = audit_ground_slopes({}, "", "dummy.tile")
    rises = result["models_ranked_by_rise_error"]
    assert all(m["mean_absolute_rise_error_m"] == 0 for m in rises)
    assert rises[0]["bits"] == 4  # Old net-rise ranking cannot distinguish.
    local = result["models_ranked_by_local_grade_error"]
    assert local[0]["bits"] == 5
    assert local[0]["segments_scored"] == 12
    assert local[0]["mean_absolute_local_grade_error"] == 0
    assert local[1]["mean_absolute_local_grade_error"] == pytest.approx(0.8)
    assert local[1]["max_absolute_local_grade_error"] == pytest.approx(0.8)
    # The model's up/down zigzags cancel as a signed bias, but do
    # NOT disappear under the residual after a constant-tilt fit.
    jagged_diag = local[1]["along_direction_bias"]
    assert jagged_diag["mean_signed_grade_error"] == pytest.approx(0)
    assert jagged_diag["mae_after_constant_tilt_diagnostic"] == pytest.approx(
        0.8
    )


def test_adjacent_grade_never_bridges_missing_hit_or_ambiguous_root(
    monkeypatch,
):
    from sm_atlas import ground_slope_audit as module
    rows = _rows()
    # One raycast misses; segments on either side must disappear.
    rows[1] = {**rows[1], "status": "not_sampled"}
    monkeypatch.setattr(
        module, "compare_ground_observations",
        lambda plan, log: {
            "world_id": 23, "terrain_surface_hits": 14, "samples": rows,
        },
    )
    roots = [
        {"index": r["index"], "status": "single_candidate",
         "candidate_world_z": [r["actual_z"] + 0.5]}
        for r in _rows()
    ]
    # A second, unrelated segment gap is due to ambiguous model roots.
    roots[6] = {"index": 6, "status": "ambiguous_multiple_candidates",
                "candidate_world_z": [81.0, 82.0]}
    monkeypatch.setattr(
        module, "compare_trilinear_hypotheses",
        lambda plan, log, tile: {"models": [
            {"bits": 5, "lattice_origin_shift_xyz": [0, 0, 0],
             "single_candidates": 14, "rmse_m": 0.5,
             "samples": roots},
        ]},
    )
    result = audit_ground_slopes({}, "", "dummy.tile")
    model = result["models_ranked_by_local_grade_error"][0]
    assert model["measured_segments"] == 10  # No cross-gap interpolation.
    assert model["segments_scored"] == 8  # Model root gap removes two more.
    assert not any(
        1 in (s["from_index"], s["to_index"])
        or 6 in (s["from_index"], s["to_index"])
        for s in model["adjacent_grade_segments"]
    )
    assert model["mean_absolute_local_grade_error"] == 0


def test_patch_gradient_detects_lateral_tilt_hidden_from_longitudinal_audit(
    monkeypatch,
):
    from sm_atlas import ground_slope_audit as module
    rows = _rows()
    monkeypatch.setattr(
        module, "compare_ground_observations",
        lambda plan, log: {
            "world_id": 23, "terrain_surface_hits": 15, "samples": rows,
        },
    )
    def candidate(offset):
        return [
            {"index": r["index"], "status": "single_candidate",
             "candidate_world_z": [r["actual_z"] + offset(i)]}
            for i, r in enumerate(rows)
        ]
    # A +0.2 m error per adjacent lane produces 0.4 m/m wrong X
    # gradient, but changes none of the twelve Y-gradient segments.
    shifted_lanes = candidate(lambda i: 0.2 * (i // 5))
    correct_shape = candidate(lambda i: 0.5)
    monkeypatch.setattr(
        module, "compare_trilinear_hypotheses",
        lambda plan, log, tile: {"models": [
            {"bits": 4, "lattice_origin_shift_xyz": [0, 0, 0],
             "single_candidates": 15, "rmse_m": 0.2,
             "samples": shifted_lanes},
            {"bits": 5, "lattice_origin_shift_xyz": [0, 0, 0],
             "single_candidates": 15, "rmse_m": 0.5,
             "samples": correct_shape},
        ]},
    )
    result = audit_ground_slopes({}, "", "dummy.tile")
    along = result["models_ranked_by_local_grade_error"]
    assert [v["bits"] for v in along] == [4, 5]
    assert all(v["mean_absolute_local_grade_error"] == 0 for v in along)
    assert all(v["mean_absolute_rise_error_m"] == 0 for v in along)
    patch = result["models_ranked_by_patch_grade_error"]
    assert [v["bits"] for v in patch] == [5, 4]
    assert patch[0]["patch_segments_scored"] == 22
    assert patch[0]["mean_absolute_patch_grade_error"] == 0
    assert patch[1]["cross_track_segments_scored"] == 10
    assert patch[1]["mean_absolute_cross_track_grade_error"] == pytest.approx(0.4)
    assert patch[1]["mean_absolute_patch_grade_error"] == pytest.approx(
        4 / 22, abs=1e-6
    )


def test_patch_does_not_bridge_missing_cross_hit_or_model_root(monkeypatch):
    from sm_atlas import ground_slope_audit as module
    rows = _rows()
    rows[5] = {**rows[5], "status": "not_sampled"}
    monkeypatch.setattr(
        module, "compare_ground_observations",
        lambda plan, log: {
            "world_id": 23, "terrain_surface_hits": 14, "samples": rows,
        },
    )
    roots = [
        {"index": r["index"], "status": "single_candidate",
         "candidate_world_z": [r["actual_z"] + 0.5]}
        for r in _rows()
    ]
    roots[11] = {
        "index": 11, "status": "ambiguous_multiple_candidates",
        "candidate_world_z": [81.0, 82.0],
    }
    monkeypatch.setattr(
        module, "compare_trilinear_hypotheses",
        lambda plan, log, tile: {"models": [
            {"bits": 5, "lattice_origin_shift_xyz": [0, 0, 0],
             "single_candidates": 14, "rmse_m": 0.5,
             "samples": roots},
        ]},
    )
    result = audit_ground_slopes({}, "", "dummy.tile")
    model = result["models_ranked_by_patch_grade_error"][0]
    assert result["measured_cross_track_segments"] == 8
    assert model["cross_track_segments_scored"] == 7
    assert model["measured_segments"] == 11
    assert model["segments_scored"] == 9
    assert model["measured_patch_segments"] == 19
    assert model["patch_segments_scored"] == 16
    assert not any(
        5 in (s["from_index"], s["to_index"])
        or 11 in (s["from_index"], s["to_index"])
        for s in model["cross_track_grade_segments"]
    )


def test_signed_directional_bias_separates_constant_tilt_from_surface_shape(
    monkeypatch,
):
    from sm_atlas import ground_slope_audit as module
    rows = _rows()
    monkeypatch.setattr(
        module, "compare_ground_observations",
        lambda plan, log: {
            "world_id": 23, "terrain_surface_hits": len(rows),
            "samples": rows,
        },
    )
    # +0.25 m per consecutive Y sample: exactly +1.0 m/m extra
    # model grade along the lane, without changing the X grade.
    model = [
        {
            "index": r["index"],
            "status": "single_candidate",
            "candidate_world_z": [r["actual_z"] + 0.25 * (i % 5)],
        }
        for i, r in enumerate(rows)
    ]
    monkeypatch.setattr(
        module, "compare_trilinear_hypotheses",
        lambda plan, log, tile: {"models": [{
            "bits": 4, "lattice_origin_shift_xyz": [0, 0, 0],
            "single_candidates": len(rows), "rmse_m": 0.6,
            "samples": model,
        }]},
    )
    result = audit_ground_slopes({}, "", "dummy.tile")
    scored = result["models_ranked_by_patch_grade_error"][0]
    along = scored["along_direction_bias"]
    cross = scored["cross_direction_bias"]
    assert scored["patch_segments_scored"] == 22
    assert along["mean_signed_grade_error"] == pytest.approx(1.0)
    assert along["mae_after_constant_tilt_diagnostic"] == pytest.approx(0)
    assert cross["mean_signed_grade_error"] == pytest.approx(0)
    assert cross["mae_after_constant_tilt_diagnostic"] == pytest.approx(0)
    # This metric is diagnostic; our original unfitted error remains large.
    assert scored["mean_absolute_local_grade_error"] == pytest.approx(1.0)


def test_directional_bias_with_no_valid_model_edges_is_unknown(monkeypatch):
    from sm_atlas import ground_slope_audit as module
    rows = _rows()
    monkeypatch.setattr(
        module, "compare_ground_observations",
        lambda plan, log: {
            "world_id": 23, "terrain_surface_hits": len(rows),
            "samples": rows,
        },
    )
    invalid = [
        {"index": r["index"], "status": "no_candidate",
         "candidate_world_z": []}
        for r in rows
    ]
    monkeypatch.setattr(
        module, "compare_trilinear_hypotheses",
        lambda plan, log, tile: {"models": [{
            "bits": 5, "lattice_origin_shift_xyz": [0, 0, 0],
            "single_candidates": 0, "rmse_m": None, "samples": invalid,
        }]},
    )
    result = audit_ground_slopes({}, "", "dummy.tile")
    model = result["models_ranked_by_patch_grade_error"][0]
    for key in ("along_direction_bias", "cross_direction_bias"):
        assert all(value is None for value in model[key].values())
    assert model["patch_segments_scored"] == 0
