from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sm_atlas.tile_file import (
    TILE_CELL_HEADER_SIZE,
    TILE_FILE_HEADER_FORMAT,
    InvalidTileFile,
    probe_tile,
)


def _write_test_tile(path: Path) -> None:
    header_size = struct.calcsize(TILE_FILE_HEADER_FORMAT)
    cell_header_offset = header_size
    cell_header_size = TILE_CELL_HEADER_SIZE

    header = struct.pack(
        TILE_FILE_HEADER_FORMAT,
        0x454C4954,
        9,
        bytes.fromhex("00112233445566778899aabbccddeeff"),
        123456789,
        1,
        1,
        cell_header_offset,
        cell_header_size,
        11,
        22,
        3,
    )

    values = [0] * 97

    # assets level 2
    values[21 + 2] = 5
    values[25 + 2] = header_size + cell_header_size
    values[29 + 2] = 8
    values[33 + 2] = 32

    # node
    values[41] = 2
    values[42] = header_size + cell_header_size + 8
    values[43] = 6
    values[44] = 24

    cell_header = struct.pack("<97i", *values)
    payload = b"12345678abcdef"

    path.write_bytes(header + cell_header + payload)


def test_probe_tile_reads_header_and_chunk_inventory(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sample.tile"
    _write_test_tile(path)

    result = probe_tile(path)

    assert result["version"] == 9
    assert result["width"] == 1
    assert result["height"] == 1
    assert result["cells"] == 1
    assert result["uuid_hex"] == (
        "00112233445566778899aabbccddeeff"
    )
    assert result["content"]["assets"] == {
        "chunks": 1,
        "items": 5,
        "compressed_bytes": 8,
        "uncompressed_bytes": 32,
    }
    assert result["content"]["node"] == {
        "chunks": 1,
        "items": 2,
        "compressed_bytes": 6,
        "uncompressed_bytes": 24,
    }
    assert result["invalid_chunk_ranges"] == []


def test_probe_tile_rejects_wrong_magic(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bad.tile"
    path.write_bytes(b"NOPE" + b"\x00" * 100)

    with pytest.raises(InvalidTileFile):
        probe_tile(path)
