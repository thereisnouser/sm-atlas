from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sm_atlas.tile_voxel_space import (
    _components, _load_density_bytes, probe_tile_voxel_space,
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


def _write_voxel_test_tile(path: Path, *, written_ff: bool = False) -> None:
    # x < 4 and x >= 12 are separate full-height 3D voids.
    # Raw byte order: z changes fastest, then y, then x.
    payload = bytearray([31]) * 4096
    for x in list(range(4)) + list(range(12, 16)):
        for y in range(16):
            for z in range(16):
                payload[x * 256 + y * 16 + z] = 0

    if written_ff:
        payload[2 * 256 + 3 * 16 + 7] = 255
    decoded = struct.pack("<iii", 0, 0, 0) + payload
    compressed = _literal_lz4(decoded)

    header = struct.pack(
        "<II16sQIIIIIII",
        0x454C4954,
        15,
        b"\x00" * 16,
        0,
        1,
        1,
        60,
        388,
        0,
        0,
        0,
    )
    values = [0] * 97
    values[93] = 1
    values[94] = 60 + 388
    values[95] = len(compressed)
    values[96] = len(decoded)
    path.write_bytes(header + struct.pack("<97i", *values) + compressed)


def test_voxel_space_finds_two_isolated_voids(tmp_path: Path) -> None:
    tile = tmp_path / "room_1x1x1.tile"
    _write_voxel_test_tile(tile)

    result = probe_tile_voxel_space(
        tile,
        min_component_size=100,
    )

    assert result["dimensions_m"] == (16, 16, 16)
    assert result["unknown_voxels"] == 0
    assert result["component_count"] == 2

    major = result["major_components"]
    assert [component["voxels"] for component in major] == [1024, 1024]
    assert sorted(component["min"][0] for component in major) == [0, 12]
    assert result["sockets"] == []


def test_voxel_space_rejects_invalid_threshold(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="density_threshold"):
        probe_tile_voxel_space(
            tmp_path / "room_1x1x1.tile",
            density_threshold=16,
        )



def test_candidate_void_components_change_under_five_bit_hypothesis() -> None:
    voxels = bytearray((111, 119))
    old_labels, old_components = _components(
        voxels, (2, 1, 1), threshold=8, density_bits=4,
    )
    five_labels, five_components = _components(
        voxels, (2, 1, 1), threshold=16, density_bits=5,
    )
    assert len(old_components) == len(five_components) == 1
    assert list(old_labels) == [0, 1]
    assert list(five_labels) == [1, 0]


def test_voxel_space_rejects_unsupported_density_bits(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="density_bits"):
        probe_tile_voxel_space(
            tmp_path / "room_1x1x1.tile",
            density_bits=6,
        )


def test_record_occupancy_is_distinct_from_literal_ff(tmp_path: Path) -> None:
    tile = tmp_path / "room_1x1x1.tile"
    _write_voxel_test_tile(tile, written_ff=True)
    values, absent, written = _load_density_bytes(
        tile, (16, 16, 16), return_written=True,
    )
    offset = (2 * 16 + 3) * 16 + 7
    assert values[offset] == 255
    assert written[offset] == 1
    assert absent == 0
    assert written.count(0) == 0
    legacy_values, legacy_absent = _load_density_bytes(tile, (16, 16, 16))
    assert legacy_values == values
    assert legacy_absent == absent

    # Reading the same single record into a deliberately larger diagnostic
    # volume leaves the second half *absent*, not a written FF.
    volume2, missing2, occupancy2 = _load_density_bytes(
        tile, (32, 16, 16), return_written=True,
    )
    assert missing2 == 16 * 16 * 16
    assert occupancy2[offset] == 1
    assert volume2[offset] == 255
    absent_offset = (20 * 16 + 3) * 16 + 7
    assert volume2[absent_offset] == 255
    assert occupancy2[absent_offset] == 0
