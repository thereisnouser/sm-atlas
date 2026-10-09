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
