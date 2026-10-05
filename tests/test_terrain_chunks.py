from __future__ import annotations

import sqlite3
from pathlib import Path
from struct import pack

from sm_atlas.database import SaveDatabase
from sm_atlas.terrain_chunks import summarize_voxel_chunks
from sm_atlas.terrain_decode import VOXELS_PER_CHUNK


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


def make_record(
    record_id: int,
    *,
    chunk_x: int,
    chunk_y: int,
    chunk_z: int,
    payload: bytes = b"test",
) -> bytes:
    raw = b"".join(
        [
            b"\x0c\x00\x01",
            pack(">I", record_id),
            b"\xff\xff\xff\xff",
            b"\x00\x00\x00\x00\x00",
            b"\x17\x00\x17",
            pack(">iii", chunk_z, chunk_y, chunk_x),
            payload,
        ]
    )
    assert len(raw) == 31 + len(payload)
    return literal_lz4_block(raw)


def test_summarize_voxel_chunks_uses_decompressed_coordinates(
    tmp_path: Path,
) -> None:
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
    connection.executemany(
        """
        INSERT INTO VoxelTerrain (id, worldId, x, y, data)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (1, 23, 0, -1, make_record(1, chunk_x=1, chunk_y=-2, chunk_z=3)),
            (2, 23, 1, -1, make_record(2, chunk_x=4, chunk_y=-3, chunk_z=4)),
        ],
    )
    connection.commit()
    connection.close()

    result = summarize_voxel_chunks(
        SaveDatabase(save_path),
        world_id=23,
        limit=100,
        examples=0,
    )

    assert result["scanned_records"] == 2
    assert result["decoded_records"] == 2
    assert result["unresolved_records"] == 0
    assert result["decode_ratio"] == 1.0
    assert result["unique_chunk_coordinates"] == 2
    assert result["chunk_bounds"] == {
        "min_x": 1,
        "max_x": 4,
        "min_y": -3,
        "max_y": -2,
        "min_z": 3,
        "max_z": 4,
    }
