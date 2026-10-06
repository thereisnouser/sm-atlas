from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Any

LUA_MAGIC = b"LUA"
LUA_VERSION = 1

TAG_NIL = 0x00
TAG_NIL_LEGACY = 0x01
TAG_BOOL = 0x02
TAG_FLOAT = 0x03
TAG_STRING = 0x04
TAG_TABLE = 0x05
TAG_INT32 = 0x06
TAG_INT16 = 0x07
TAG_INT8 = 0x08
TAG_JSON = 0x09
TAG_DOUBLE = 0x0B
TAG_USERDATA = 0x64

UD_UUID = 10001
UD_VEC3 = 10003
UD_QUAT = 10004
UD_COLOR = 10005

HANDLE_USERDATA_KINDS = {
    10021,
    10023,
    10024,
    10025,
    10027,
    10028,
    10030,
    10036,
    10037,
    10039,
}


class LuaValueError(ValueError):
    """Raised when a Scrap Mechanic LUA value stream cannot be decoded."""


@dataclass(frozen=True)
class LuaUuid:
    value: bytes

    def __post_init__(self) -> None:
        if len(self.value) != 16:
            raise ValueError("UUID must contain 16 bytes")

    def __str__(self) -> str:
        hex_value = self.value.hex()
        return (
            f"{hex_value[0:8]}-"
            f"{hex_value[8:12]}-"
            f"{hex_value[12:16]}-"
            f"{hex_value[16:20]}-"
            f"{hex_value[20:32]}"
        )


@dataclass(frozen=True)
class LuaVec3:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class LuaQuat:
    x: float
    y: float
    z: float
    w: float


@dataclass(frozen=True)
class LuaColor:
    r: float
    g: float
    b: float
    a: float


@dataclass(frozen=True)
class LuaHandle:
    kind: int
    value: int


class BitReader:
    def __init__(self, data: bytes, *, bit_position: int = 0) -> None:
        self.data = data
        self.bit_position = bit_position

    @property
    def remaining_bits(self) -> int:
        return len(self.data) * 8 - self.bit_position

    def _require(self, bit_count: int) -> None:
        if bit_count < 0:
            raise ValueError("bit_count must be non-negative")
        if self.bit_position + bit_count > len(self.data) * 8:
            raise LuaValueError(
                f"truncated LUA stream at bit {self.bit_position}: "
                f"need {bit_count} more bits"
            )

    def read_bits(self, bit_count: int) -> int:
        self._require(bit_count)

        if bit_count == 0:
            return 0

        start_bit = self.bit_position
        start_byte = start_bit // 8
        end_bit = start_bit + bit_count
        end_byte = (end_bit + 7) // 8

        chunk = int.from_bytes(
            self.data[start_byte:end_byte],
            "big",
        )
        leading_bits = start_bit - start_byte * 8
        total_bits = (end_byte - start_byte) * 8
        shift = total_bits - leading_bits - bit_count

        self.bit_position = end_bit
        return (chunk >> shift) & ((1 << bit_count) - 1)

    def read_u8(self) -> int:
        return self.read_bits(8)

    def read_u16(self) -> int:
        return self.read_bits(16)

    def read_u32(self) -> int:
        return self.read_bits(32)

    def read_i8(self) -> int:
        value = self.read_u8()
        return value - 0x100 if value & 0x80 else value

    def read_i16(self) -> int:
        value = self.read_u16()
        return value - 0x10000 if value & 0x8000 else value

    def read_i32(self) -> int:
        value = self.read_u32()
        return value - 0x100000000 if value & 0x80000000 else value

    def read_bool(self) -> bool:
        return bool(self.read_bits(1))

    def read_f32(self) -> float:
        raw = self.read_u32().to_bytes(4, "big")
        return struct.unpack(">f", raw)[0]

    def read_f64(self) -> float:
        raw = self.read_bits(64).to_bytes(8, "big")
        return struct.unpack(">d", raw)[0]

    def align_byte(self) -> None:
        remainder = self.bit_position % 8
        if remainder:
            self.bit_position += 8 - remainder

    def read_bytes(
        self,
        length: int,
        *,
        align: bool = False,
    ) -> bytes:
        if length < 0:
            raise LuaValueError("negative byte length")

        if align:
            self.align_byte()

        if self.bit_position % 8 == 0:
            self._require(length * 8)
            start = self.bit_position // 8
            end = start + length
            self.bit_position += length * 8
            return self.data[start:end]

        return bytes(self.read_u8() for _ in range(length))


class LuaDecoder:
    def __init__(
        self,
        data: bytes,
        *,
        max_depth: int = 256,
        max_table_items: int = 1_000_000,
        max_string_bytes: int = 32 * 1024 * 1024,
    ) -> None:
        self.data = data
        self.max_depth = max_depth
        self.max_table_items = max_table_items
        self.max_string_bytes = max_string_bytes
        self.reader = BitReader(data)

    def decode(self) -> Any:
        if len(self.data) < 7:
            raise LuaValueError("LUA stream is too short")

        magic = self.reader.read_bytes(3)
        if magic != LUA_MAGIC:
            raise LuaValueError(f"invalid LUA magic: {magic!r}")

        version = self.reader.read_u32()
        if version != LUA_VERSION:
            raise LuaValueError(
                f"unsupported LUA serialization version: {version}"
            )

        return self._decode_value(depth=0)

    def _decode_value(self, *, depth: int) -> Any:
        if depth > self.max_depth:
            raise LuaValueError("maximum LUA nesting depth exceeded")

        tag_bit_position = self.reader.bit_position
        tag = self.reader.read_u8()

        if tag in (TAG_NIL, TAG_NIL_LEGACY):
            return None

        if tag == TAG_BOOL:
            return self.reader.read_bool()

        if tag == TAG_FLOAT:
            return self.reader.read_f32()

        if tag == TAG_DOUBLE:
            return self.reader.read_f64()

        if tag == TAG_STRING:
            length = self.reader.read_u32()
            if length > self.max_string_bytes:
                raise LuaValueError(
                    f"string is too large: {length} bytes"
                )
            raw = self.reader.read_bytes(length, align=True)
            return raw.decode("utf-8", "replace")

        if tag == TAG_JSON:
            length = self.reader.read_u32()
            if length > self.max_string_bytes:
                raise LuaValueError(
                    f"JSON value is too large: {length} bytes"
                )
            raw = self.reader.read_bytes(length, align=True)
            text = raw.decode("utf-8", "replace")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text

        if tag == TAG_TABLE:
            return self._decode_table(depth=depth)

        if tag == TAG_INT32:
            return self.reader.read_i32()

        if tag == TAG_INT16:
            return self.reader.read_i16()

        if tag == TAG_INT8:
            return self.reader.read_i8()

        if tag == TAG_USERDATA:
            return self._decode_userdata(
                tag_bit_position=tag_bit_position,
            )

        raise LuaValueError(
            f"unknown LUA tag 0x{tag:02x} "
            f"at bit {tag_bit_position}"
        )

    def _decode_table(self, *, depth: int) -> dict[Any, Any]:
        count = self.reader.read_u32()
        if count > self.max_table_items:
            raise LuaValueError(
                f"table is too large: {count} items"
            )

        is_array = self.reader.read_bool()
        result: dict[Any, Any] = {}

        if is_array:
            start_index = self.reader.read_i32()
            for index in range(count):
                result[start_index + index] = self._decode_value(
                    depth=depth + 1
                )
            return result

        for _ in range(count):
            key = self._decode_value(depth=depth + 1)
            value = self._decode_value(depth=depth + 1)

            try:
                result[key] = value
            except TypeError as exc:
                raise LuaValueError(
                    f"unhashable LUA table key: {key!r}"
                ) from exc

        return result

    def _decode_userdata(
        self,
        *,
        tag_bit_position: int,
    ) -> Any:
        kind = self.reader.read_u32()

        if kind == UD_UUID:
            raw = self.reader.read_bytes(16)
            return LuaUuid(raw[::-1])

        if kind == UD_VEC3:
            return LuaVec3(
                self.reader.read_f32(),
                self.reader.read_f32(),
                self.reader.read_f32(),
            )

        if kind == UD_QUAT:
            return LuaQuat(
                self.reader.read_f32(),
                self.reader.read_f32(),
                self.reader.read_f32(),
                self.reader.read_f32(),
            )

        if kind == UD_COLOR:
            return LuaColor(
                self.reader.read_f32(),
                self.reader.read_f32(),
                self.reader.read_f32(),
                self.reader.read_f32(),
            )

        if kind in HANDLE_USERDATA_KINDS:
            return LuaHandle(
                kind=kind,
                value=self.reader.read_u32(),
            )

        raise LuaValueError(
            f"unknown LUA userdata kind {kind} "
            f"at bit {tag_bit_position}"
        )


def decode_lua_value(data: bytes) -> Any:
    return LuaDecoder(data).decode()


def to_jsonable(value: Any) -> Any:
    if isinstance(value, LuaUuid):
        return {
            "type": "uuid",
            "value": str(value),
        }

    if isinstance(value, LuaVec3):
        return {
            "type": "vec3",
            "x": value.x,
            "y": value.y,
            "z": value.z,
        }

    if isinstance(value, LuaQuat):
        return {
            "type": "quat",
            "x": value.x,
            "y": value.y,
            "z": value.z,
            "w": value.w,
        }

    if isinstance(value, LuaColor):
        return {
            "type": "color",
            "r": value.r,
            "g": value.g,
            "b": value.b,
            "a": value.a,
        }

    if isinstance(value, LuaHandle):
        return {
            "type": "handle",
            "kind": value.kind,
            "value": value.value,
        }

    if isinstance(value, dict):
        return {
            str(key): to_jsonable(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [to_jsonable(item) for item in value]

    return value
