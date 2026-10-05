from __future__ import annotations

import sqlite3
from pathlib import Path
from struct import pack

from sm_atlas.database import SaveDatabase
from sm_atlas.formats.generic_data import WORLD_MARKER_UID
from sm_atlas.formats.lz4 import decompress_block
from sm_atlas.worlds import discover_worlds


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


def test_lz4_literal_block_round_trip() -> None:
    payload = b"hello Scrap Mechanic"

    assert decompress_block(literal_lz4_block(payload)) == payload


def test_discover_worlds(tmp_path: Path) -> None:
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

    payload = make_world_payload(
        123456,
        "$SURVIVAL_DATA/Scripts/game/worlds/Overworld.lua",
        "Overworld",
        '{"depth":0}',
    )
    envelope = make_world_envelope(1, payload)

    connection.execute(
        """
        INSERT INTO GenericData (uid, key, worldId, flags, data)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            WORLD_MARKER_UID,
            pack("<I", 1),
            1,
            3,
            envelope,
        ),
    )
    connection.commit()
    connection.close()

    worlds = discover_worlds(SaveDatabase(save_path))

    assert len(worlds) == 1
    assert worlds[0].world_id == 1
    assert worlds[0].seed == 123456
    assert worlds[0].classname == "Overworld"
    assert worlds[0].terrain == {"depth": 0}
