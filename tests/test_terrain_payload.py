from __future__ import annotations

import sqlite3
from pathlib import Path
from struct import pack

from sm_atlas.database import SaveDatabase
from sm_atlas.terrain_decode import VOXELS_PER_CHUNK
from sm_atlas.terrain_payload import probe_voxel_payloads


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


def make_outer_record(
    record_id: int,
    *,
    chunk_x: int,
    chunk_y: int,
    chunk_z: int,
    payload: bytes,
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
    return literal_lz4_block(raw)


def test_payload_probe_finds_inner_lz4_and_four_byte_state(
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

    voxels = bytes([0x41]) * VOXELS_PER_CHUNK
    inner = literal_lz4_block(voxels)

    connection.executemany(
        """
        INSERT INTO VoxelTerrain (id, worldId, x, y, data)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                1,
                23,
                0,
                -1,
                make_outer_record(
                    1,
                    chunk_x=1,
                    chunk_y=-2,
                    chunk_z=3,
                    payload=b"\xaa\xbb" + inner,
                ),
            ),
            (
                2,
                23,
                0,
                -1,
                make_outer_record(
                    2,
                    chunk_x=2,
                    chunk_y=-3,
                    chunk_z=4,
                    payload=b"\x00\x00\x00\x01",
                ),
            ),
        ],
    )
    connection.commit()
    connection.close()

    result = probe_voxel_payloads(
        SaveDatabase(save_path),
        world_id=23,
        limit=10,
        max_offset=4,
        examples=10,
    )

    assert result["decoded_records"] == 2
    assert result["four_byte_records"] == 1
    assert result["four_byte_values"] == {"00000001": 1}
    assert result["inner_lz4_matches"] == 1
    assert result["inner_lz4_offset_histogram"] == {"2": 1}
    assert result["exact_inner_lz4_records"] == 0
