from __future__ import annotations

from pathlib import Path
import struct

import pytest

from sm_atlas.tile_file import InvalidTileFile
from sm_atlas.tile_objects import (
    probe_tile_objects,
    placements_near_candidate_route,
)


def _literal_lz4(data: bytes) -> bytes:
    length = len(data)
    output = bytearray((min(length, 15) << 4,))
    if length >= 15:
        length -= 15
        while length >= 255:
            output.append(255)
            length -= 255
        output.append(length)
    output.extend(data)
    return bytes(output)


def _make_tile(path: Path, *, corrupt_unknown: bool = False) -> None:
    header_size = struct.calcsize("<II16sQIIIIIII")
    cell_header_size = 388
    hdr = struct.pack(
        "<II16sQIIIIIII",
        0x454C4954, 15, b"\x00" * 16, 0,
        1, 1, header_size, cell_header_size, 0, 0, 0,
    )
    transform = struct.pack(
        "<3f4f3f",
        4.5, 5.0, 6.25,
        1.0, 0.0, 0.0, 0.0,
        0.25, 0.5, 1.25,
    )
    uid_unknown = bytes.fromhex("00112233445566778899aabbccddeeff")
    uid_harvestable = bytes.fromhex("ffeeddccbbaa99887766554433221100")
    unknown = transform + uid_unknown + bytes(13 + int(corrupt_unknown))
    harvestable = transform + uid_harvestable + bytes(9)

    chunk_a = _literal_lz4(unknown)
    chunk_b = _literal_lz4(harvestable)
    off_a = header_size + cell_header_size
    off_b = off_a + len(chunk_a)
    ints = [0] * 97
    # "unknown": count, index, compressed bytes, decoded bytes.
    ints[89:93] = [1, off_a, len(chunk_a), len(unknown)]
    # "harvestable", first of 4 LODs.
    ints[57] = 1
    ints[61] = off_b
    ints[65] = len(chunk_b)
    ints[69] = len(harvestable)
    path.write_bytes(
        hdr + struct.pack("<97i", *ints) + chunk_a + chunk_b
    )


def test_object_probe_reads_unknown_and_harvestable_transforms(
    tmp_path: Path,
) -> None:
    tile = tmp_path / "fixture_1x1x1.tile"
    _make_tile(tile)
    result = probe_tile_objects(tile)

    assert result["total_placements"] == 2
    assert result["by_kind"] == {"harvestable": 1, "unknown": 1}
    assert len(result["groups"]) == 2

    a, b = result["placements"]
    assert a["kind"] == "harvestable" or a["kind"] == "unknown"
    by_kind = {x["kind"]: x for x in result["placements"]}
    u = by_kind["unknown"]
    assert u["tile_position"] == (4.5, 5.0, 6.25)
    assert u["scale"] == (0.25, 0.5, 1.25)
    assert u["rotation"] == (1.0, 0.0, 0.0, 0.0)
    assert u["uuid_hex"] == "00112233445566778899aabbccddeeff"
    assert len(u["trailing_bytes_hex"]) == 26
    assert by_kind["harvestable"]["uuid_hex"] == (
        "ffeeddccbbaa99887766554433221100"
    )
    assert len(by_kind["harvestable"]["trailing_bytes_hex"]) == 18


def test_object_probe_rejects_unsupported_record_stride(tmp_path: Path) -> None:
    tile = tmp_path / "fixture_1x1x1.tile"
    _make_tile(tile, corrupt_unknown=True)
    with pytest.raises(InvalidTileFile, match="unsupported unknown"):
        probe_tile_objects(tile)


def test_object_probe_rejects_negative_example_count(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="examples"):
        probe_tile_objects(tmp_path / "fixture_1x1x1.tile", examples=-1)



def test_placement_proximity_is_to_record_origin_not_collision_shape() -> None:
    placements = [
        {
            "kind": "unknown",
            "index": 2,
            "cell": 0,
            "uuid_hex": "abcd",
            "tile_position": (1.5, 0.5, 1.5),
        },
        {
            "kind": "harvestable",
            "index": 7,
            "cell": 0,
            "uuid_hex": "ffff",
            "tile_position": (8.0, 9.0, 1.5),
        },
    ]
    near = placements_near_candidate_route(
        placements, [(0, 0, 1), (1, 0, 1)],
        radius_m=1,
    )
    assert len(near) == 1
    assert near[0]["index"] == 2
    assert near[0]["distance_to_footpath_m"] == 0
    assert near[0]["nearest_foot"] == (1, 0, 1)


def test_placement_proximity_rejects_empty_radius() -> None:
    with pytest.raises(ValueError, match="radius_m"):
        placements_near_candidate_route([], [(0, 0, 1)], radius_m=0)
