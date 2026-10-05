from __future__ import annotations

import sqlite3
from pathlib import Path
from struct import pack

from sm_atlas.database import SaveDatabase
from sm_atlas.terrain_decode import (
    EXPECTED_RECORD_SIZE,
    VOXELS_PER_CHUNK,
    decode_voxel_record,
    probe_decompressed_voxel_terrain,
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


def make_uncompressed_record(
    record_id: int,
    *,
    chunk_x: int,
    chunk_y: int,
    chunk_z: int,
    voxel: int = 0x01,
) -> bytes:
    header = b"".join(
        [
            b"\x0c\x00\x01",
            pack(">I", record_id),
            b"\xff\xff\xff\xff",
            b"\x00\x00\x00\x00\x00",
            b"\x17\x00\x17",
            pack(">iii", chunk_z, chunk_y, chunk_x),
        ]
    )
    assert len(header) == 31

    return header + bytes([voxel]) * VOXELS_PER_CHUNK


def test_decode_voxel_record_after_lz4() -> None:
    raw = make_uncompressed_record(
        2027,
        chunk_x=1,
        chunk_y=-2,
        chunk_z=3,
        voxel=0x41,
    )
    assert len(raw) == EXPECTED_RECORD_SIZE

    record, failure = decode_voxel_record(
        record_id=2027,
        cell_x=0,
        cell_y=-1,
        blob=literal_lz4_block(raw),
    )

    assert failure is None
    assert record is not None
    assert (record.chunk_x, record.chunk_y, record.chunk_z) == (1, -2, 3)
    assert record.exact_voxel_payload is True
    assert record.material_counts == {1: VOXELS_PER_CHUNK}
    assert record.zero_density_voxels == 0
    assert record.nonzero_density_voxels == VOXELS_PER_CHUNK


def test_probe_decompressed_voxel_terrain(tmp_path: Path) -> None:
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

    rows = []
    for index in range(3):
        record_id = 100 + index
        raw = make_uncompressed_record(
            record_id,
            chunk_x=index,
            chunk_y=-1,
            chunk_z=index,
        )
        rows.append(
            (
                record_id,
                23,
                0,
                -1,
                literal_lz4_block(raw),
            )
        )

    connection.executemany(
        """
        INSERT INTO VoxelTerrain (id, worldId, x, y, data)
        VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )
    connection.commit()
    connection.close()

    result = probe_decompressed_voxel_terrain(
        SaveDatabase(save_path),
        world_id=23,
        limit=10,
        examples=2,
    )

    assert result["scanned_records"] == 3
    assert result["decoded_records"] == 3
    assert result["decode_ratio"] == 1.0
    assert result["exact_voxel_payload_records"] == 3
    assert result["unique_chunk_coordinates"] == 3
    assert result["duplicate_coordinate_records"] == 0
    assert result["decompressed_size_histogram"] == {
        str(EXPECTED_RECORD_SIZE): 3
    }
