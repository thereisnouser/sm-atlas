from __future__ import annotations

import sqlite3
from pathlib import Path
from struct import pack

from sm_atlas.database import SaveDatabase
from sm_atlas.terrain_data import decode_terrain_data_candidates


class BitWriter:
    def __init__(self) -> None:
        self.bits: list[int] = []

    def write_bits(self, value: int, count: int) -> None:
        for shift in range(count - 1, -1, -1):
            self.bits.append((value >> shift) & 1)

    def u8(self, value: int) -> None:
        self.write_bits(value, 8)

    def u32(self, value: int) -> None:
        self.write_bits(value & 0xFFFFFFFF, 32)

    def bit(self, value: bool) -> None:
        self.bits.append(1 if value else 0)

    def align(self) -> None:
        while len(self.bits) % 8:
            self.bits.append(0)

    def raw(self, data: bytes, *, align: bool = False) -> None:
        if align:
            self.align()
        for byte in data:
            self.u8(byte)

    def build(self) -> bytes:
        self.align()
        output = bytearray()
        for offset in range(0, len(self.bits), 8):
            value = 0
            for bit in self.bits[offset:offset + 8]:
                value = (value << 1) | bit
            output.append(value)
        return bytes(output)


def string(writer: BitWriter, value: str) -> None:
    data = value.encode()
    writer.u8(0x04)
    writer.u32(len(data))
    writer.raw(data, align=True)


def empty_table(writer: BitWriter) -> None:
    writer.u8(0x05)
    writer.u32(0)
    writer.bit(False)


def lua_terrain_blob() -> bytes:
    writer = BitWriter()
    writer.raw(b"LUA")
    writer.u32(1)

    writer.u8(0x05)
    writer.u32(3)
    writer.bit(False)

    string(writer, "bounds")
    empty_table(writer)
    string(writer, "tunnels")
    empty_table(writer)
    string(writer, "spawners")
    empty_table(writer)

    return writer.build()


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


def script_envelope(raw: bytes, world_id: int) -> bytes:
    key = b"terrain"
    compressed = literal_lz4_block(raw)
    return b"".join(
        [
            bytes.fromhex("00112233445566778899aabbccddeeff"),
            pack(">H", len(key)),
            key,
            pack(">H", world_id),
            bytes([7]),
            pack(">I", len(compressed)),
            compressed,
        ]
    )


def test_decode_terrain_data_candidates(tmp_path: Path) -> None:
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
    connection.execute(
        """
        INSERT INTO ScriptData (uid, key, worldId, flags, data)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            b"uid",
            b"key",
            23,
            7,
            script_envelope(lua_terrain_blob(), 23),
        ),
    )
    connection.commit()
    connection.close()

    result = decode_terrain_data_candidates(
        SaveDatabase(save_path),
        world_id=23,
        limit=100,
        examples=10,
    )

    assert result["terrain_candidates"] == 1
    candidate = result["candidates"][0]
    assert candidate["signal_keys"] == [
        "bounds",
        "spawners",
        "tunnels",
    ]
