from __future__ import annotations

from math import sqrt

import pytest

from sm_atlas.ground_normal_field_audit import (
    _gradient_local_to_world,
    _normal_at_observed_hit,
    audit_ground_field_normals,
)


def _field():
    dims = (5, 5, 5)
    volume = bytearray(len(range(125)))
    written = bytearray([1]) * len(volume)
    # Around (x,y,z)=(1.4,1.4,1.25), this is an exactly linear
    # scalar function with gradient (-1,-2,-3); neighbouring values
    # remain in the 4-bit range and are not clipped.
    for x in range(5):
        for y in range(5):
            for z in range(5):
                raw = max(0, 15 - x - 2 * y - 3 * z)
                volume[(x * 5 + y) * 5 + z] = raw
    return volume, dims, written


def _observed_normal():
    return (-2 / sqrt(14), 1 / sqrt(14), 3 / sqrt(14))


def test_world_rotation_maps_voxel_gradient_consistently():
    gradient = (1.0, 2.0, -3.0)
    assert _gradient_local_to_world(gradient, 0) == (1, 2, -3)
    assert _gradient_local_to_world(gradient, 1) == (-2, 1, -3)
    assert _gradient_local_to_world(gradient, 2) == (-1, -2, -3)
    assert _gradient_local_to_world(gradient, 3) == (2, -1, -3)
    with pytest.raises(ValueError, match="rotation"):
        _gradient_local_to_world(gradient, 4)


def test_correct_trilinear_gradient_matches_game_normal_after_tile_rotation():
    v, dims, written = _field()
    sample = _normal_at_observed_hit(
        v, dims, written, [1.4, 1.4, 1.25], _observed_normal(),
        mask=15, shift=(0, 0, 0), rotation=1,
    )
    assert sample["status"] == "sampled"
    assert sample["on_voxel_grid_plane"] is False
    assert sample["normal_angle_error_degrees"] == pytest.approx(0, abs=1e-5)
    assert sample["model_world_normal"] == pytest.approx(
        _observed_normal(), abs=1e-5
    )
    assert sample["model_world_grade_xy"] == pytest.approx(
        [2 / 3, -1 / 3], abs=1e-5
    )
    assert sample["game_world_grade_xy"] == pytest.approx(
        [2 / 3, -1 / 3], abs=1e-5
    )


def test_wrong_physics_normal_has_large_direction_mismatch():
    v, dims, written = _field()
    r = _normal_at_observed_hit(
        v, dims, written, [1.4, 1.4, 1.25], (0.0, 0.0, 1.0),
        mask=15, shift=(0, 0, 0), rotation=1,
    )
    assert r["status"] == "sampled"
    assert r["normal_angle_error_degrees"] > 30


def test_missing_record_or_non_falling_field_fails_closed():
    v, dims, written = _field()
    index = (1 * 5 + 1) * 5 + 2
    written[index] = 0
    r = _normal_at_observed_hit(
        v, dims, written, [1.4, 1.4, 1.25], _observed_normal(),
        mask=15, shift=(0, 0, 0), rotation=1,
    )
    assert r["status"] == "missing_neighbour_or_boundary"
    assert r["normal_angle_error_degrees"] is None
    written[index] = 1
    # Reversing the Z-density ordering must not be treated as a
    # plausible upward ground surface for this encoding hypothesis.
    for x in range(5):
        for y in range(5):
            for z in range(5):
                v[(x * 5 + y) * 5 + z] = z
    r = _normal_at_observed_hit(
        v, dims, written, [1.4, 1.4, 1.25], _observed_normal(),
        mask=15, shift=(0, 0, 0), rotation=1,
    )
    assert r["status"] == "density_not_falling_upward"


def test_voxel_grid_plane_is_flagged_not_silently_trusted():
    v, dims, written = _field()
    r = _normal_at_observed_hit(
        v, dims, written, [1.0, 1.4, 1.25], _observed_normal(),
        mask=15, shift=(0, 0, 0), rotation=1,
    )
    assert r["status"] == "sampled"
    assert r["on_voxel_grid_plane"] is True


def test_integration_ranks_model_angle_with_saved_tile_rotation(monkeypatch):
    from sm_atlas import ground_normal_field_audit as module
    volume, dims, written = _field()
    actual_normal = _observed_normal()
    samples = [
        {"index": i, "local_xyz": [x, y, 1.25]}
        for i, (x, y) in enumerate((
            (1.2, 1.3), (1.4, 1.5), (1.6, 1.7),
        ))
    ]
    monkeypatch.setattr(
        module, "inspect_ground_density",
        lambda plan, log, tile: {
            "world_id": 23,
            "tile_path": "dummy_1x1x1.tile",
            "samples": samples,
        },
    )
    monkeypatch.setattr(
        module, "compare_ground_observations",
        lambda plan, log: {
            "world_id": 23,
            "samples": [
                {"index": s["index"],
                 "status": "terrain_surface_hit",
                 "normal_world": actual_normal,
                 "fraction": s["index"] / 2,
                 "lateral_offset_m": 0.0}
                for s in samples
            ],
        },
    )
    monkeypatch.setattr(module, "_dimensions", lambda path: dims)
    monkeypatch.setattr(
        module, "_load_density_bytes",
        lambda path, dims, *, return_written=False: (
            (volume, 0, written)
            if return_written else (volume, 0)
        ),
    )
    result = audit_ground_field_normals(
        {"layout_rotation_quarter_turns": 1}, "", "dummy.tile",
        include_six_bit=True,
    )
    assert result["models_evaluated"] == 24
    assert result["measured_hits"] == 3
    assert result["six_bit_hypothesis_opted_in"] is True
    candidate = next(m for m in result["models_ranked_by_normal_angle"]
                     if m["bits"] == 4 and
                     m["lattice_origin_shift_xyz"] == [0, 0, 0])
    assert candidate["samples_scored"] == 3
    assert candidate["mean_normal_angle_error_degrees"] == pytest.approx(
        0, abs=1e-5,
    )
    assert candidate["grid_plane_samples_scored"] == 0
    default = audit_ground_field_normals(
        {"layout_rotation_quarter_turns": 1}, "", "dummy.tile",
    )
    assert default["models_evaluated"] == 16


def test_invalid_placement_rotation_fails_instead_of_guessing(monkeypatch):
    from sm_atlas import ground_normal_field_audit as module
    monkeypatch.setattr(
        module, "inspect_ground_density",
        lambda plan, log, tile: {
            "tile_path": "dummy.tile", "samples": [],
        },
    )
    monkeypatch.setattr(
        module, "compare_ground_observations",
        lambda plan, log: {"samples": []},
    )
    with pytest.raises(ValueError, match="rotation"):
        audit_ground_field_normals(
            {"layout_rotation_quarter_turns": 5}, "", "dummy.tile",
        )


def test_normal_audit_command_remains_explicitly_read_only():
    from sm_atlas.cli import build_parser
    parser = build_parser()
    args = parser.parse_args([
        "tile-ground-normal-audit", "plan.json", "hits.log", "cave.tile",
        "--include-6-bit", "--json",
    ])
    assert args.include_6_bit is True
    assert args.json is True
    assert parser.parse_args([
        "tile-ground-normal-audit", "plan.json", "hits.log", "cave.tile",
    ]).include_6_bit is False
