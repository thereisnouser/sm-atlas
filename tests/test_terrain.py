from __future__ import annotations

import sqlite3
from pathlib import Path
from struct import pack

from sm_atlas.database import SaveDatabase
from sm_atlas.formats.generic_data import WORLD_MARKER_UID
from sm_atlas.terrain import summarize_voxel_terrain


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


def make_world_payload(
    seed: int,
    filename: str,
    classname: str,
    terrain_params: str,
) -> bytes:
    output = bytearray(pack(">I", seed))

    for value in (filename, classname, terrain_params):
        encoded = value.encode("utf-8")
        output.extend(pack(">H", len(encoded)))
        output.extend(encoded)

    return bytes(output)


def make_world_envelope(world_id: int, payload: bytes) -> bytes:
    compressed = literal_lz4_block(payload)

    return b"".join(
        [
            WORLD_MARKER_UID,
            pack(">H", 4),
            pack("<I", world_id),
            pack(">H", world_id),
            pack("<I", 3),
            bytes([len(compressed)]),
            compressed,
        ]
    )


def test_summarize_voxel_terrain(tmp_path: Path) -> None:
    save_path = tmp_path / "save.db"
    connection = sqlite3.connect(save_path)

    connection.execute(
        """
        CREATE TABLE GenericData (
            uid BLOB,
            key BLOB,
            worldId INTEGER,
            flags INTEGER,
            data BLOB
        )
        """
    )
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

    payload = make_world_payload(
        123,
        "$SURVIVAL_DATA/Scripts/game/worlds/UndergroundWorld.lua",
        "UndergroundWorldMiningHub",
        '{"depth":1,"worldFilePath":"undergroundworld_mininghub.world"}',
    )

    connection.execute(
        """
        INSERT INTO GenericData (uid, key, worldId, flags, data)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            WORLD_MARKER_UID,
            pack("<I", 12),
            12,
            3,
            make_world_envelope(12, payload),
        ),
    )

    connection.executemany(
        """
        INSERT INTO VoxelTerrain (worldId, x, y, data)
        VALUES (?, ?, ?, ?)
        """,
        [
            (12, -2, -3, b"abc"),
            (12, -2, -3, b"12345"),
            (12, 4, 7, b"x"),
            (99, 1, 2, b"zz"),
        ],
    )

    connection.commit()
    connection.close()

    summaries = summarize_voxel_terrain(
        SaveDatabase(save_path),
        underground_only=True,
    )

    assert len(summaries) == 1

    summary = summaries[0]
    assert summary.world_id == 12
    assert summary.kind == "underground"
    assert summary.depth == 1
    assert summary.records == 3
    assert summary.unique_coordinates == 2
    assert summary.min_x == -2
    assert summary.max_x == 4
    assert summary.min_y == -3
    assert summary.max_y == 7
    assert summary.total_blob_bytes == 9
    assert summary.min_blob_bytes == 1
    assert summary.max_blob_bytes == 5
    assert summary.records_per_coordinate == 1.5
