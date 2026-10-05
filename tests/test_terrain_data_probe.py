from __future__ import annotations

import sqlite3
from pathlib import Path
from struct import pack

from sm_atlas.database import SaveDatabase
from sm_atlas.terrain_data_probe import (
    decode_script_data_envelope,
    probe_terrain_script_data,
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


def make_envelope(
    raw: bytes,
    *,
    world_id: int = 23,
    key: bytes = b"test",
    flags: int = 7,
) -> bytes:
    compressed = literal_lz4_block(raw)
    return b"".join(
        [
            bytes.fromhex("00112233445566778899aabbccddeeff"),
            pack(">H", len(key)),
            key,
            pack(">H", world_id),
            bytes([flags]),
            pack(">I", len(compressed)),
            compressed,
        ]
    )


def test_decode_script_data_envelope() -> None:
    raw = b"LUA" + bytes(range(16))
    envelope = decode_script_data_envelope(make_envelope(raw))

    assert envelope.world_id == 23
    assert envelope.flags == 7
    assert envelope.key == b"test"
    assert envelope.data == raw


def test_probe_finds_lua_payload(tmp_path: Path) -> None:
    save_path = tmp_path / "save.db"
    connection = sqlite3.connect(save_path)
    connection.execute(
        """
        CREATE TABLE ScriptData (
            uid BLOB,
            key BLOB,
            worldId INTEGER,
            flags INTEGER,
            data BLOB
        )
        """
    )

    blob = make_envelope(b"LUA" + b"terrain-grid")
    connection.execute(
        """
        INSERT INTO ScriptData (uid, key, worldId, flags, data)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            bytes.fromhex("00112233445566778899aabbccddeeff"),
            b"test",
            23,
            7,
            blob,
        ),
    )
    connection.commit()
    connection.close()

    result = probe_terrain_script_data(
        SaveDatabase(save_path),
        world_id=23,
        limit=10,
        examples=10,
    )

    assert result["scanned_records"] == 1
    assert result["decoded_envelopes"] == 1
    assert result["decode_failures"] == {}
    assert result["lua_records"] == 1
    assert result["largest_lua_records"][0]["raw_size"] == 15
