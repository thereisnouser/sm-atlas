from __future__ import annotations

import struct

from sm_atlas.formats.lua_values import (
    LuaUuid,
    LuaVec3,
    decode_lua_value,
)


class BitWriter:
    def __init__(self) -> None:
        self.bits: list[int] = []

    def write_bits(self, value: int, count: int) -> None:
        for shift in range(count - 1, -1, -1):
            self.bits.append((value >> shift) & 1)

    def write_u8(self, value: int) -> None:
        self.write_bits(value & 0xFF, 8)

    def write_u32(self, value: int) -> None:
        self.write_bits(value & 0xFFFFFFFF, 32)

    def write_i32(self, value: int) -> None:
        self.write_u32(value)

    def write_bool(self, value: bool) -> None:
        self.bits.append(1 if value else 0)

    def align(self) -> None:
        while len(self.bits) % 8:
            self.bits.append(0)

    def write_bytes(self, data: bytes, *, align: bool = False) -> None:
        if align:
            self.align()
        for byte in data:
            self.write_u8(byte)

    def build(self) -> bytes:
        self.align()
        result = bytearray()
        for offset in range(0, len(self.bits), 8):
            value = 0
            for bit in self.bits[offset:offset + 8]:
                value = (value << 1) | bit
            result.append(value)
        return bytes(result)


def write_string(writer: BitWriter, value: str) -> None:
    encoded = value.encode("utf-8")
    writer.write_u8(0x04)
    writer.write_u32(len(encoded))
    writer.write_bytes(encoded, align=True)


def write_int32(writer: BitWriter, value: int) -> None:
    writer.write_u8(0x06)
    writer.write_i32(value)


def test_decode_map_and_array() -> None:
    writer = BitWriter()
    writer.write_bytes(b"LUA")
    writer.write_u32(1)

    writer.write_u8(0x05)
    writer.write_u32(2)
    writer.write_bool(False)

    write_string(writer, "name")
    write_string(writer, "D6")

    write_string(writer, "values")
    writer.write_u8(0x05)
    writer.write_u32(3)
    writer.write_bool(True)
    writer.write_i32(-1)
    write_int32(writer, 10)
    write_int32(writer, 20)
    write_int32(writer, 30)

    value = decode_lua_value(writer.build())

    assert value["name"] == "D6"
    assert value["values"] == {
        -1: 10,
        0: 20,
        1: 30,
    }


def test_decode_userdata_uuid_and_vec3() -> None:
    writer = BitWriter()
    writer.write_bytes(b"LUA")
    writer.write_u32(1)

    writer.write_u8(0x05)
    writer.write_u32(2)
    writer.write_bool(False)

    write_string(writer, "uuid")
    writer.write_u8(0x64)
    writer.write_u32(10001)
    stored_uuid = bytes(range(16))
    writer.write_bytes(stored_uuid)

    write_string(writer, "position")
    writer.write_u8(0x64)
    writer.write_u32(10003)
    for value in (1.5, -2.0, 3.25):
        raw = struct.pack(">f", value)
        writer.write_u32(int.from_bytes(raw, "big"))

    value = decode_lua_value(writer.build())

    assert isinstance(value["uuid"], LuaUuid)
    assert value["uuid"].value == stored_uuid[::-1]
    assert value["position"] == LuaVec3(1.5, -2.0, 3.25)
