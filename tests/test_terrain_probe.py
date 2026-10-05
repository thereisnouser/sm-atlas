from __future__ import annotations

import sqlite3
from pathlib import Path

from sm_atlas.database import SaveDatabase
from sm_atlas.formats.lz4 import decompress_block_prefix
from sm_atlas.terrain_probe import (
    VOXELS_PER_CHUNK,
    find_lz4_candidates,
    probe_voxel_terrain,
)


def literal_lz4_block(data: bytes) -> bytes:
    length = len(data)
    output = bytearray()

    if length < 15:
        output.append(length << 4)
    else:
        output.append(0xF0)
        remaining = length - 15

        while remaining >= 255:
            output.append(255)
            remaining -= 255

        output.append(remaining)

    output.extend(data)
    return bytes(output)


def test_decompress_block_prefix_ignores_trailer() -> None:
    payload = b"hello"
    encoded = literal_lz4_block(payload) + b"trailer"

    result, consumed = decompress_block_prefix(
        encoded,
        expected_output_size=len(payload),
    )

    assert result == payload
    assert consumed == len(literal_lz4_block(payload))


def test_find_lz4_candidates_finds_embedded_chunk() -> None:
    voxels = bytes([0x01]) * VOXELS_PER_CHUNK
    compressed = literal_lz4_block(voxels)
    blob = b"HEADER" + compressed + b"TAIL"

    candidates = find_lz4_candidates(blob, max_offset=16)

    assert candidates
    assert candidates[0].offset == len(b"HEADER")
    assert candidates[0].compressed_size == len(compressed)
    assert candidates[0].nonzero_density == VOXELS_PER_CHUNK


def test_probe_voxel_terrain(tmp_path: Path) -> None:
    save_path = tmp_path / "save.db"
    connection = sqlite3.connect(save_path)
    connection.execute(
        """
        CREATE TABLE VoxelTerrain (
            id INTEGER PRIMARY KEY,
            worldId INTEGER,
            x INTEGER,
            y INTEGER,
            data BLOB
        )
        """
    )

    voxels = bytes([0x40]) * VOXELS_PER_CHUNK
    blob = b"ABCD" + literal_lz4_block(voxels)

    connection.execute(
        """
        INSERT INTO VoxelTerrain (worldId, x, y, data)
        VALUES (?, ?, ?, ?)
        """,
        (12, -2, -3, blob),
    )
    connection.commit()
    connection.close()

    result = probe_voxel_terrain(
        SaveDatabase(save_path),
        world_id=12,
        limit=10,
        max_offset=16,
    )

    assert result["scanned_records"] == 1
    assert result["matched_records"] == 1
    assert result["offset_histogram"] == {"4": 1}

    candidate = result["records"][0]["lz4_candidates"][0]
    assert candidate["offset"] == 4
    assert candidate["material_counts"] == {1: VOXELS_PER_CHUNK}
