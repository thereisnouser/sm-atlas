from __future__ import annotations

import sqlite3
from pathlib import Path
from struct import pack

from sm_atlas.database import SaveDatabase
from sm_atlas.terrain_density_probe import probe_density_streams


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


def pack_six_bit(values: list[int]) -> bytes:
    bits = "".join(f"{value:06b}" for value in values)
    bits += "0" * ((8 - len(bits) % 8) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, "big")


def make_outer_record(
    record_id: int,
    *,
    x: int,
    body: bytes,
) -> bytes:
    payload = b"\x05" + len(body).to_bytes(2, "big") + body
    raw = b"".join(
        [
            b"\x0c\x00\x01",
            pack(">I", record_id),
            b"\xff\xff\xff\xff",
            b"\x00\x00\x00\x00\x00",
            b"\x17\x00\x17",
            pack(">iii", 0, -1, x),
            payload,
        ]
    )
    return literal_lz4_block(raw)


def test_density_probe_scores_matching_neighbor_faces(
    tmp_path: Path,
) -> None:
    axis = 17
    voxel_count = axis ** 3

    left = [0] * voxel_count
    right = [0] * voxel_count

    for y in range(axis):
        for z in range(axis):
            value = ((y + z) % 62) + 1
            left[z + axis * y + axis * axis * 16] = value
            right[z + axis * y] = value

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
            (
                1,
                23,
                0,
                -1,
                make_outer_record(
                    1,
                    x=0,
                    body=pack_six_bit(left),
                ),
            ),
            (
                2,
                23,
                0,
                -1,
                make_outer_record(
                    2,
                    x=1,
                    body=pack_six_bit(right),
                ),
            ),
        ],
    )
    connection.commit()
    connection.close()

    result = probe_density_streams(
        SaveDatabase(save_path),
        world_id=23,
        limit=10,
        max_byte_offset=0,
        max_pairs=10,
    )

    matching = [
        model
        for model in result["models"]
        if (
            model["mode"] == "05"
            and model["byte_offset"] == 0
            and model["bit_offset"] == 0
            and model["bit_order"] == "msb"
            and model["fill"] == 0
        )
    ]

    assert matching
    model = matching[0]
    assert model["face_pairs"] == 1
    assert model["exact_ratio"] == 1.0
    assert model["active_exact_ratio"] == 1.0
    assert model["observed_exact_ratio"] == 1.0
    assert model["observed_active_exact_ratio"] == 1.0
    assert model["observed_coverage"] == 1.0
