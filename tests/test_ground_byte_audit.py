from __future__ import annotations

import pytest

from sm_atlas.ground_byte_audit import audit_ground_voxel_bytes


def _example_volume():
    dims = (4, 4, 8)
    data = bytearray(0 for _ in range(4 * 4 * 8))
    present = bytearray([1]) * len(data)
    for x in range(dims[0]):
        for y in range(dims[1]):
            index = (x * dims[1] + y) * dims[2]
            data[index + 2] = 0x1F
            data[index + 3] = 0x0F
            data[index + 4] = 0x00
    return dims, data, present


def _mock_real_raycast_profile(monkeypatch, *, z=3.4):
    from sm_atlas import ground_byte_audit as module
    dims, data, present = _example_volume()
    # Same XY integer column, two different real game ray positions.
    # Must not falsely double the amount of independent byte evidence.
    samples = [
        {"index": 0, "local_xyz": [1.1, 1.2, z]},
        {"index": 1, "local_xyz": [1.2, 1.1, z + 0.01]},
    ]
    monkeypatch.setattr(
        module, "inspect_ground_density",
        lambda plan, log, tile: {
            "world_id": 23, "tile_uuid": "sample-uuid",
            "tile_path": "not-read-directly.tile",
            "samples": samples,
        },
    )
    monkeypatch.setattr(module, "_dimensions", lambda path: dims)
    monkeypatch.setattr(
        module, "_load_density_bytes",
        lambda path, requested, *, return_written=False: (
            (data, present.count(0), present)
            if return_written else (data, present.count(0))
        ),
    )
    return data, present, dims


def test_byte_audit_uses_unique_xy_voxel_columns_and_two_vertical_origins(
    monkeypatch,
):
    _mock_real_raycast_profile(monkeypatch)
    result = audit_ground_voxel_bytes({}, "", "tile.tile", radius_voxels=0)
    assert result["game_ray_hits"] == 2
    assert result["unique_voxel_columns"] == 1
    original, half = result["shifts"]
    assert original["recorded_pairs"] == 1
    assert half["recorded_pairs"] == 1
    assert original["pairs"][0]["sample_z_indices"] == [3, 4]
    assert half["pairs"][0]["sample_z_indices"] == [2, 3]
    assert original["pairs"][0]["raw_below"] == 15
    assert original["pairs"][0]["raw_above"] == 0
    assert half["pairs"][0]["raw_below"] == 31
    assert half["pairs"][0]["raw_above"] == 15
    assert original["masked_midpoint_checks"][0][
        "solid_below_air_above"
    ] == 1
    assert original["bit_transitions"][0]["set_to_clear"] == 1
    assert original["bit_transitions"][7]["unchanged"] == 1
    assert result["written_ff_voxels_in_tile"] == 0


def test_byte_audit_borrows_only_nearest_real_z_and_never_invents_missing(
    monkeypatch,
):
    data, present, dims = _mock_real_raycast_profile(monkeypatch)
    # XY radius 1 yields 9 unique columns, regardless of number of rays.
    empty_index = (0 * dims[1] + 1) * dims[2] + 4
    present[empty_index] = 0
    ff_index = (1 * dims[1] + 1) * dims[2] + 3
    data[ff_index] = 255  # Recorded data, not absent.
    result = audit_ground_voxel_bytes({}, "", "tile.tile", radius_voxels=1)
    assert result["unique_voxel_columns"] == 9
    assert result["absent_voxels_in_tile"] == 1
    assert result["written_ff_voxels_in_tile"] == 1
    original = result["shifts"][0]
    assert original["recorded_pairs"] == 8
    assert original["missing_or_out_of_bounds_pairs"] == 1
    assert len(original["pairs"]) == 9
    assert any(
        p["raw_below"] == 255 and p["status"] == "recorded_pair"
        for p in original["pairs"]
    )
    assert any(
        p["status"] == "unwritten_voxel" and p["raw_below"] is None
        for p in original["pairs"]
    )
    assert sum(p["count"] for p in original["common_raw_pairs"]) == 8


def test_invalid_nearby_radius_is_rejected_before_file_access():
    for radius in (-1, 4, 0.5, True):
        with pytest.raises(ValueError, match="radius_voxels"):
            audit_ground_voxel_bytes(
                {}, "", "dummy.tile", radius_voxels=radius,
            )


def test_ground_byte_audit_cli_parser():
    from sm_atlas.cli import build_parser
    args = build_parser().parse_args([
        "tile-ground-byte-audit", "plan.json", "hits.log", "cave.tile",
        "--radius", "2", "--json",
    ])
    assert args.plan.name == "plan.json"
    assert args.log.name == "hits.log"
    assert args.tile.name == "cave.tile"
    assert args.radius == 2
    assert args.json is True
