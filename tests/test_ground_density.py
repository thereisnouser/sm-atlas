from __future__ import annotations

from pathlib import Path

import pytest

from sm_atlas.ground_density import inspect_ground_density
from sm_atlas.ground_truth import compare_ground_observations


UUID = "a7bde4a1-89f1-4493-8331-270ba1dae561"
DIMS = (32, 48, 32)


def _plan():
    samples = [
        {
            "world_xy": [44.5, -107.5],
            "estimated_surface_world_z": 82.1667,
            "fraction": 0.0,
            "lateral_offset_m": 0.0,
        },
        {
            "world_xy": [44.5, -107.75],
            "estimated_surface_world_z": 82.475,
            "fraction": 0.25,
            "lateral_offset_m": 0.0,
        },
    ]
    return {
        "world_id": 23, "node_id": 322,
        "tile_uuid": UUID,
        "tile_dimensions_m": list(DIMS),
        "layout_rotation_quarter_turns": 1,
        "world_bounds": {
            "min": [32, -112, 64], "max": [80, -80, 96],
        },
        "alignment": {"status": "two_or_more_independent_tunnel_anchors"},
        "critical_edge": {"world_samples": samples},
    }


def _log():
    return (
        "[Lua] ATLAS_GROUND,0,1,44.500000,-107.500000,"
        "82.166700,23,81.833336,-0.131712,0.381266,0.915035,voxelTerrain\n"
        "[Lua] ATLAS_GROUND,1,1,44.500000,-107.750000,"
        "82.475000,23,81.860001,-0.137880,0.105052,0.984862,voxelTerrain"
    )


def _fixture(monkeypatch, tile_path: Path):
    from sm_atlas import ground_density

    tile_path.write_bytes(b"fixture mocked LZ4 voxels")
    monkeypatch.setattr(
        ground_density, "probe_tile",
        lambda tile: {"uuid_hex": UUID.replace("-", "")},
    )
    volume = bytearray([255]) * (DIMS[0] * DIMS[1] * DIMS[2])
    for x in (3, 4):
        for z, raw in ((16, 0x10), (17, 0x1F), (18, 0x01), (19, 0x00)):
            volume[(x * DIMS[1] + 35) * DIMS[2] + z] = raw
    monkeypatch.setattr(
        ground_density, "_load_density_bytes",
        lambda path, dims, *, return_written=False: (
            (volume, volume.count(255), bytearray(
                0 if raw == 255 else 1 for raw in volume
            ))
            if return_written else (volume, volume.count(255))
        ),
    )


def test_profile_uses_observed_world_to_tile_xy_and_reads_raw_bytes(
    monkeypatch, tmp_path,
):
    tile = tmp_path / "passage_2x3x2.tile"
    _fixture(monkeypatch, tile)
    assert compare_ground_observations(_plan(), _log())["terrain_surface_hits"] == 2

    result = inspect_ground_density(_plan(), _log(), tile, z_margin=2)
    assert result["world_id"] == 23
    assert result["hits"] == 2
    assert result["observed_local_z_range"] == [17.833336, 17.860001]
    assert result["samples"][0]["local_xyz"] == [4.5, 35.5, 17.833336]
    assert result["samples"][1]["local_xyz"] == [4.25, 35.5, 17.860001]
    assert len(result["columns"]) == 1
    column = result["columns"][0]
    assert column["local_xy"] == [4, 35]
    assert column["sample_indexes"] == [0, 1]
    vals = {row["z"]: row for row in column["raw_vertical_bytes"]}
    assert vals[17]["raw_hex"] == "1F"
    assert vals[17]["low4"] == 15
    assert vals[17]["low5"] == 31
    assert vals[18]["raw"] == 1
    assert vals[17]["unknown_or_ff"] is False
    assert vals[15]["unknown_or_ff"] is True
    assert vals[15]["missing_record"] is True
    assert vals[15]["record_present"] is False
    assert vals[15]["literal_ff"] is False
    assert vals[17]["record_present"] is True
    assert vals[17]["literal_ff"] is False
    assert vals[15]["low4"] is None
    assert 81.5 in column["candidate_vertical_crossings_world_z"]["4"]
    assert 81.5 in column["candidate_vertical_crossings_world_z"]["5"]
    assert "not" in result["warning"].lower()


def test_profile_rejects_wrong_tile_and_world(monkeypatch, tmp_path):
    tile = tmp_path / "passage_2x3x2.tile"
    _fixture(monkeypatch, tile)
    from sm_atlas import ground_density
    original = ground_density.probe_tile
    monkeypatch.setattr(
        ground_density, "probe_tile",
        lambda path: {"uuid_hex": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
    )
    with pytest.raises(ValueError, match="UUID"):
        inspect_ground_density(_plan(), _log(), tile)
    monkeypatch.setattr(ground_density, "probe_tile", original)

    wrong_dims = _plan()
    wrong_dims["tile_dimensions_m"] = [16, 48, 32]
    with pytest.raises(ValueError, match="dimensions"):
        inspect_ground_density(wrong_dims, _log(), tile)
    wrong_world = _log().replace(",23,81.833336", ",12,81.833336")
    with pytest.raises(ValueError, match="does not match"):
        inspect_ground_density(_plan(), wrong_world, tile)


def test_profile_rejects_invalid_margin_and_absent_actual_hits(
    monkeypatch, tmp_path,
):
    tile = tmp_path / "passage_2x3x2.tile"
    _fixture(monkeypatch, tile)
    with pytest.raises(ValueError, match="z_margin"):
        inspect_ground_density(_plan(), _log(), tile, z_margin=-1)
    with pytest.raises(ValueError, match="no upward"):
        inspect_ground_density(
            _plan(), _log().replace("voxelTerrain", "terrainAsset"), tile,
        )


def test_profile_cli_arguments_are_read_only():
    from sm_atlas.cli import build_parser

    args = build_parser().parse_args([
        "tile-ground-profile", "plan.json", "atlas_ground_hits.log",
        "passage_2x3x2.tile", "--z-margin", "4", "--json",
    ])
    assert args.plan.name == "plan.json"
    assert args.log.name == "atlas_ground_hits.log"
    assert args.tile.name == "passage_2x3x2.tile"
    assert args.z_margin == 4
    assert args.json is True


def test_profile_preserves_written_ff_and_marks_missing_slots(
    monkeypatch, tmp_path,
):
    from sm_atlas import ground_density
    tile = tmp_path / "passage_2x3x2.tile"
    _fixture(monkeypatch, tile)
    # Use the same synthetic tile shape, but distinguish an FF explicitly
    # present in a record from a missing byte at the adjacent Z index.
    volume = bytearray([255]) * (DIMS[0] * DIMS[1] * DIMS[2])
    written = bytearray([0]) * len(volume)
    x, y = 4, 35
    for z, raw in ((16, 255), (17, 0), (18, 255), (19, 0)):
        i = (x * DIMS[1] + y) * DIMS[2] + z
        volume[i] = raw
        written[i] = 1
    monkeypatch.setattr(
        ground_density, "_load_density_bytes",
        lambda path, dims, *, return_written=False: (
            (volume, written.count(0), written)
            if return_written else (volume, written.count(0))
        ),
    )
    report = inspect_ground_density(_plan(), _log(), tile, z_margin=2)
    col = next(item for item in report["columns"] if item["local_xy"] == [4, 35])
    vals = {entry["z"]: entry for entry in col["raw_vertical_bytes"]}
    assert vals[16]["raw"] == 255
    assert vals[16]["record_present"] is True
    assert vals[16]["literal_ff"] is True
    assert vals[16]["low4"] == 15
    assert vals[16]["low5"] == 31
    assert vals[18]["literal_ff"] is True
    assert vals[15]["missing_record"] is True
    assert vals[15]["low4"] is None
    assert report["written_ff_voxels_in_tile"] == 2
