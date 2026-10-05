from __future__ import annotations

import sqlite3
from pathlib import Path
from struct import pack

from sm_atlas.database import SaveDatabase
from sm_atlas.terrain_decode import VOXELS_PER_CHUNK
from sm_atlas.terrain_mask_probe import MASK_BYTES, probe_voxel_masks


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


def make_outer_record(record_id: int, payload: bytes) -> bytes:
    raw = b"".join(
        [
            b"\x0c\x00\x01",
            pack(">I", record_id),
            b"\xff\xff\xff\xff",
            b"\x00\x00\x00\x00\x00",
            b"\x17\x00\x17",
            pack(">iii", 0, -1, 0),
            payload,
        ]
    )
    return literal_lz4_block(raw)


def test_mask_probe_finds_mask_plus_byte_values(
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

    mask = bytearray(MASK_BYTES)
    selected = [0, 5, 100, VOXELS_PER_CHUNK - 1]

    for bit_index in selected:
        mask[bit_index // 8] |= 1 << (7 - (bit_index % 8))

    body = bytes(mask) + bytes([1, 2, 3, 4])
    payload = b"\x05" + len(body).to_bytes(2, "big") + body

    connection.execute(
        """
        INSERT INTO VoxelTerrain (id, worldId, x, y, data)
        VALUES (?, ?, ?, ?, ?)
        """,
        (1, 23, 0, -1, make_outer_record(1, payload)),
    )
    connection.commit()
    connection.close()

    result = probe_voxel_masks(
        SaveDatabase(save_path),
        world_id=23,
        limit=10,
        max_offset=0,
    )

    matching = [
        model
        for model in result["models"]
        if (
            model["mode"] == "05"
            and model["offset"] == 0
            and model["selected_bits"] == "ones"
            and model["value_bits"] == 8
        )
    ]

    assert result["mask_bytes"] == 615
    assert matching
    assert matching[0]["exact_records"] == 1
