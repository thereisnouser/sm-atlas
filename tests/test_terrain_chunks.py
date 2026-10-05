from __future__ import annotations

import sqlite3
from pathlib import Path
from struct import pack

from sm_atlas.database import SaveDatabase
from sm_atlas.terrain_chunks import (
    parse_voxel_chunk_record,
    summarize_voxel_chunks,
)


def make_blob(
    record_id: int,
    *,
    chunk_x: int,
    chunk_y: int,
    chunk_z: int,
    prefix: bytes = b"\xc0",
    payload: bytes = b"\x05\x01payload",
) -> bytes:
    return b"".join(
        [
            prefix,
            b"\x0c\x00\x01",
            pack(">I", record_id),
            b"\xff\xff\xff\xff",
            b"\x00\x01\x00\xff",
            b"\x05\x17\x00\x17",
            pack(">iii", chunk_z, chunk_y, chunk_x),
            payload,
        ]
    )


def test_parse_voxel_chunk_record_uses_zyx_coordinates() -> None:
    record = parse_voxel_chunk_record(
        record_id=2038,
        cell_x=1,
        cell_y=-1,
        blob=make_blob(
            2038,
            chunk_x=4,
            chunk_y=-2,
            chunk_z=3,
            prefix=b"\xff\x15",
        ),
    )

    assert record is not None
    assert record.coordinate == (4, -2, 3)
    assert record.prefix_hex == "ff15"
    assert record.payload_prefix_hex.startswith("0501")


def test_parse_voxel_chunk_record_rejects_wrong_cell() -> None:
    record = parse_voxel_chunk_record(
        record_id=2038,
        cell_x=0,
        cell_y=-1,
        blob=make_blob(
            2038,
            chunk_x=4,
            chunk_y=-2,
            chunk_z=3,
        ),
    )

    assert record is None


def test_summarize_voxel_chunks_tracks_duplicates(tmp_path: Path) -> None:
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
            (1, 23, 0, -1, make_blob(1, chunk_x=1, chunk_y=-2, chunk_z=3)),
            (2, 23, 0, -1, make_blob(2, chunk_x=1, chunk_y=-2, chunk_z=3)),
            (3, 23, 1, -1, make_blob(3, chunk_x=4, chunk_y=-3, chunk_z=4)),
            (4, 23, 0, -1, b"unresolved"),
        ],
    )
    connection.commit()
    connection.close()

    result = summarize_voxel_chunks(
        SaveDatabase(save_path),
        world_id=23,
        limit=100,
        examples=10,
    )

    assert result["scanned_records"] == 4
    assert result["decoded_records"] == 3
    assert result["unresolved_records"] == 1
    assert result["unique_chunk_coordinates"] == 2
    assert result["duplicate_coordinates"] == 1
    assert result["duplicate_coordinate_records"] == 1
    assert result["chunk_bounds"] == {
        "min_x": 1,
        "max_x": 4,
        "min_y": -3,
        "max_y": -2,
        "min_z": 3,
        "max_z": 4,
    }
