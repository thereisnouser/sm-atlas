from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from .database import SaveDatabase


UNRESOLVED_WORLD_ID = 65535


@dataclass(frozen=True)
class PortalInfo:
    portal_id: int
    world_id_a: int
    x_a: int
    y_a: int
    world_id_b: int
    x_b: int
    y_b: int
    decoded: DecodedPortalBlob | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "portal_id": self.portal_id,
            "world_id_a": self.world_id_a,
            "x_a": self.x_a,
            "y_a": self.y_a,
            "world_id_b": self.world_id_b,
            "x_b": self.x_b,
            "y_b": self.y_b,
            "decoded": (
                None
                if self.decoded is None
                else self.decoded.to_dict()
            ),
        }


def discover_portals(
    database: SaveDatabase,
) -> list[PortalInfo]:
    with database.connect() as connection:
        if "Portal" not in database._tables(connection):
            return []

        rows = connection.execute(
            """
            SELECT id, worldIdA, xA, yA, worldIdB, xB, yB, data
            FROM Portal
            ORDER BY id
            """
        ).fetchall()

    return [
        PortalInfo(
            portal_id=int(row["id"]),
            world_id_a=int(row["worldIdA"]),
            x_a=int(row["xA"]),
            y_a=int(row["yA"]),
            world_id_b=int(row["worldIdB"]),
            x_b=int(row["xB"]),
            y_b=int(row["yB"]),
            decoded=decode_portal_blob(
                bytes(row["data"] or b"")
            ),
        )
        for row in rows
    ]


@dataclass(frozen=True)
class DecodedPortalBlob:
    dimensions: tuple[float, float, float]
    side_a_prefix: int
    world_id_a: int
    position_a: tuple[float, float, float]
    rotation_a: tuple[float, float, float, float]
    side_b_prefix: int | None
    world_id_b: int | None
    position_b: tuple[float, float, float] | None
    rotation_b: tuple[float, float, float, float] | None
    tail_bit_offset: int
    tail_bits: str

    def to_dict(self) -> dict[str, object]:
        return {
            "complete": self.position_b is not None,
            "dimensions": list(self.dimensions),
            "side_a": {
                "prefix": self.side_a_prefix,
                "world_id": self.world_id_a,
                "position": list(self.position_a),
                "rotation": list(self.rotation_a),
                "cell": list(_position_to_cell(self.position_a)),
            },
            "side_b": (
                None
                if (
                    self.world_id_b is None
                    or self.position_b is None
                    or self.rotation_b is None
                )
                else {
                    "prefix": self.side_b_prefix,
                    "world_id": self.world_id_b,
                    "position": list(self.position_b),
                    "rotation": list(self.rotation_b),
                    "cell": list(_position_to_cell(self.position_b)),
                }
            ),
            "tail_bit_offset": self.tail_bit_offset,
            "tail_bits": self.tail_bits,
        }


@dataclass(frozen=True)
class PortalProbe:
    portal_id: int
    world_id_a: int
    x_a: int
    y_a: int
    world_id_b: int
    x_b: int
    y_b: int
    blob_size: int
    blob_hex: str
    header: dict[str, object] | None
    header_matches_columns: bool | None
    decoded: DecodedPortalBlob | None
    decoded_matches_columns: bool | None
    float32_be_from_29: tuple[dict[str, object], ...]
    opening_a_position_candidate: tuple[float, float, float] | None


def _decode_portal_blob_header(
    data: bytes,
) -> dict[str, object] | None:
    if len(data) < 29:
        return None

    return {
        "prefix": data[0],
        "marker": int.from_bytes(
            data[1:3],
            "big",
            signed=False,
        ),
        "id": int.from_bytes(
            data[3:7],
            "big",
            signed=False,
        ),
        "side_a_flag": data[7],
        "y_a": int.from_bytes(
            data[8:12],
            "big",
            signed=True,
        ),
        "x_a": int.from_bytes(
            data[12:16],
            "big",
            signed=True,
        ),
        "world_id_a": int.from_bytes(
            data[16:18],
            "big",
            signed=False,
        ),
        "side_b_flag": data[18],
        "y_b": int.from_bytes(
            data[19:23],
            "big",
            signed=True,
        ),
        "x_b": int.from_bytes(
            data[23:27],
            "big",
            signed=True,
        ),
        "world_id_b": int.from_bytes(
            data[27:29],
            "big",
            signed=False,
        ),
    }


def _header_matches_columns(
    header: dict[str, object] | None,
    *,
    portal_id: int,
    world_id_a: int,
    x_a: int,
    y_a: int,
    world_id_b: int,
    x_b: int,
    y_b: int,
) -> bool | None:
    if header is None:
        return None

    return (
        header["id"] == portal_id
        and header["world_id_a"] == world_id_a
        and header["x_a"] == x_a
        and header["y_a"] == y_a
        and header["world_id_b"] == world_id_b
        and header["x_b"] == x_b
        and header["y_b"] == y_b
    )


def _read_unsigned_bits(
    data: bytes,
    bit_offset: int,
    bit_count: int,
) -> int:
    if bit_offset < 0:
        raise ValueError("bit_offset must be non-negative")
    if bit_count < 0:
        raise ValueError("bit_count must be non-negative")
    if bit_offset + bit_count > len(data) * 8:
        raise ValueError("requested bits exceed portal blob")

    value = 0
    for offset in range(bit_offset, bit_offset + bit_count):
        byte = data[offset // 8]
        shift = 7 - (offset % 8)
        value = (value << 1) | ((byte >> shift) & 1)
    return value


def _read_float32_bits(
    data: bytes,
    bit_offset: int,
) -> float:
    raw = _read_unsigned_bits(data, bit_offset, 32)
    return float(
        struct.unpack(
            ">f",
            raw.to_bytes(4, "big"),
        )[0]
    )


def _read_float_tuple(
    data: bytes,
    bit_offset: int,
    count: int,
) -> tuple[float, ...]:
    return tuple(
        _read_float32_bits(data, bit_offset + index * 32)
        for index in range(count)
    )


def _position_to_cell(
    position: tuple[float, float, float],
    *,
    cell_size: float = 64.0,
) -> tuple[int, int]:
    if cell_size <= 0.0:
        raise ValueError("cell_size must be positive")

    return (
        math.floor(position[0] / cell_size),
        math.floor(position[1] / cell_size),
    )


def decode_portal_blob(
    data: bytes,
) -> DecodedPortalBlob | None:
    """Decode the experimentally identified transform section of Portal.data.

    The first 29 bytes are the fixed database/header mirror. Bytes 29..40 are
    an aligned Vec3 of portal dimensions. The remaining known transform fields
    are bit-packed MSB-first, so side A/B fields are not byte-aligned.
    """

    minimum_side_a_bits = 570
    if len(data) * 8 < minimum_side_a_bits:
        return None

    dimensions = _read_float_tuple(data, 29 * 8, 3)
    bit_offset = 41 * 8

    side_a_prefix = _read_unsigned_bits(data, bit_offset, 2)
    bit_offset += 2
    world_id_a = _read_unsigned_bits(data, bit_offset, 16)
    bit_offset += 16
    position_a = _read_float_tuple(data, bit_offset, 3)
    bit_offset += 3 * 32
    rotation_a = _read_float_tuple(data, bit_offset, 4)
    bit_offset += 4 * 32

    side_b_prefix = None
    world_id_b = None
    position_b = None
    rotation_b = None

    if len(data) * 8 >= 812:
        side_b_prefix = _read_unsigned_bits(data, bit_offset, 2)
        bit_offset += 2
        world_id_b = _read_unsigned_bits(data, bit_offset, 16)
        bit_offset += 16
        position_b = _read_float_tuple(data, bit_offset, 3)
        bit_offset += 3 * 32
        rotation_b = _read_float_tuple(data, bit_offset, 4)
        bit_offset += 4 * 32

    numeric_values = (
        *dimensions,
        *position_a,
        *rotation_a,
        *(() if position_b is None else position_b),
        *(() if rotation_b is None else rotation_b),
    )
    if not all(math.isfinite(value) for value in numeric_values):
        return None

    remaining_bits = len(data) * 8 - bit_offset
    tail_bits = (
        format(
            _read_unsigned_bits(data, bit_offset, remaining_bits),
            f"0{remaining_bits}b",
        )
        if remaining_bits
        else ""
    )

    return DecodedPortalBlob(
        dimensions=(
            float(dimensions[0]),
            float(dimensions[1]),
            float(dimensions[2]),
        ),
        side_a_prefix=side_a_prefix,
        world_id_a=world_id_a,
        position_a=(
            float(position_a[0]),
            float(position_a[1]),
            float(position_a[2]),
        ),
        rotation_a=(
            float(rotation_a[0]),
            float(rotation_a[1]),
            float(rotation_a[2]),
            float(rotation_a[3]),
        ),
        side_b_prefix=side_b_prefix,
        world_id_b=world_id_b,
        position_b=(
            None
            if position_b is None
            else (
                float(position_b[0]),
                float(position_b[1]),
                float(position_b[2]),
            )
        ),
        rotation_b=(
            None
            if rotation_b is None
            else (
                float(rotation_b[0]),
                float(rotation_b[1]),
                float(rotation_b[2]),
                float(rotation_b[3]),
            )
        ),
        tail_bit_offset=bit_offset,
        tail_bits=tail_bits,
    )


def _decoded_matches_columns(
    decoded: DecodedPortalBlob | None,
    *,
    world_id_a: int,
    x_a: int,
    y_a: int,
    world_id_b: int,
    x_b: int,
    y_b: int,
) -> bool | None:
    if decoded is None:
        return None

    side_a_matches = (
        decoded.world_id_a == world_id_a
        and _position_to_cell(decoded.position_a) == (x_a, y_a)
    )
    if not side_a_matches:
        return False

    if decoded.position_b is None:
        return (
            world_id_b == UNRESOLVED_WORLD_ID
            and (x_b, y_b) == (0, 0)
        )

    return (
        decoded.world_id_b == world_id_b
        and _position_to_cell(decoded.position_b) == (x_b, y_b)
    )


def _opening_a_position_candidate(
    data: bytes,
) -> tuple[float, float, float] | None:
    if len(data) < 41:
        return None

    values = struct.unpack(
        ">3f",
        data[29:41],
    )
    if not all(math.isfinite(value) for value in values):
        return None

    return tuple(float(value) for value in values)


def _common_prefix_length(
    values: list[bytes],
) -> int:
    if not values:
        return 0

    limit = min(len(value) for value in values)
    for index in range(limit):
        byte = values[0][index]
        if any(value[index] != byte for value in values[1:]):
            return index
    return limit


def _common_suffix_length(
    values: list[bytes],
) -> int:
    if not values:
        return 0

    limit = min(len(value) for value in values)
    for size in range(1, limit + 1):
        byte = values[0][-size]
        if any(value[-size] != byte for value in values[1:]):
            return size - 1
    return limit


def _scan_aligned_be_floats(
    data: bytes,
    *,
    start: int = 29,
) -> tuple[dict[str, object], ...]:
    values = []

    for offset in range(start, len(data) - 3, 4):
        value = struct.unpack(
            ">f",
            data[offset:offset + 4],
        )[0]

        if not math.isfinite(value):
            display: float | str = str(value)
        else:
            display = round(float(value), 9)

        values.append(
            {
                "offset": offset,
                "hex": data[offset:offset + 4].hex(),
                "value": display,
            }
        )

    return tuple(values)


def probe_portals(
    database: SaveDatabase,
    *,
    world_id: int | None = None,
    portal_id: int | None = None,
) -> list[PortalProbe]:
    with database.connect() as connection:
        database._require_table(connection, "Portal")

        clauses = []
        params: list[int] = []

        if world_id is not None:
            clauses.append(
                "(worldIdA = ? OR worldIdB = ?)"
            )
            params.extend((world_id, world_id))

        if portal_id is not None:
            clauses.append("id = ?")
            params.append(portal_id)

        where = (
            " WHERE " + " AND ".join(clauses)
            if clauses
            else ""
        )
        rows = connection.execute(
            """
            SELECT
                id,
                worldIdA,
                xA,
                yA,
                worldIdB,
                xB,
                yB,
                data
            FROM Portal
            """
            + where
            + " ORDER BY id",
            tuple(params),
        ).fetchall()

    probes = []

    for row in rows:
        data = bytes(row["data"] or b"")
        header = _decode_portal_blob_header(data)
        decoded = decode_portal_blob(data)
        probes.append(
            PortalProbe(
                portal_id=int(row["id"]),
                world_id_a=int(row["worldIdA"]),
                x_a=int(row["xA"]),
                y_a=int(row["yA"]),
                world_id_b=int(row["worldIdB"]),
                x_b=int(row["xB"]),
                y_b=int(row["yB"]),
                blob_size=len(data),
                blob_hex=data.hex(),
                header=header,
                header_matches_columns=_header_matches_columns(
                    header,
                    portal_id=int(row["id"]),
                    world_id_a=int(row["worldIdA"]),
                    x_a=int(row["xA"]),
                    y_a=int(row["yA"]),
                    world_id_b=int(row["worldIdB"]),
                    x_b=int(row["xB"]),
                    y_b=int(row["yB"]),
                ),
                decoded=decoded,
                decoded_matches_columns=_decoded_matches_columns(
                    decoded,
                    world_id_a=int(row["worldIdA"]),
                    x_a=int(row["xA"]),
                    y_a=int(row["yA"]),
                    world_id_b=int(row["worldIdB"]),
                    x_b=int(row["xB"]),
                    y_b=int(row["yB"]),
                ),
                float32_be_from_29=_scan_aligned_be_floats(
                    data,
                ),
                opening_a_position_candidate=(
                    _opening_a_position_candidate(data)
                ),
            )
        )

    return probes


def summarize_portal_probe(
    probes: list[PortalProbe],
) -> list[dict[str, object]]:
    return [
        {
            "id": probe.portal_id,
            "world_a": {
                "id": probe.world_id_a,
                "cell": [probe.x_a, probe.y_a],
            },
            "world_b": {
                "id": probe.world_id_b,
                "cell": [probe.x_b, probe.y_b],
            },
            "blob_size": probe.blob_size,
            "blob_hex": probe.blob_hex,
            "header": probe.header,
            "header_matches_columns": (
                probe.header_matches_columns
            ),
            "decoded": (
                None
                if probe.decoded is None
                else probe.decoded.to_dict()
            ),
            "decoded_matches_columns": (
                probe.decoded_matches_columns
            ),
            "opening_a_position_candidate": (
                None
                if probe.opening_a_position_candidate is None
                else [
                    round(value, 6)
                    for value
                    in probe.opening_a_position_candidate
                ]
            ),
            "float32_be_from_29": list(
                probe.float32_be_from_29
            ),
        }
        for probe in probes
    ]


def compare_portal_payloads(
    database: SaveDatabase,
    *,
    world_id: int,
    side: str = "a",
) -> list[dict[str, object]]:
    normalized_side = side.strip().lower()
    if normalized_side not in {"a", "b"}:
        raise ValueError("side must be 'a' or 'b'")

    column = (
        "worldIdA"
        if normalized_side == "a"
        else "worldIdB"
    )

    with database.connect() as connection:
        database._require_table(connection, "Portal")
        rows = connection.execute(
            f"""
            SELECT
                id,
                worldIdA,
                xA,
                yA,
                worldIdB,
                xB,
                yB,
                data
            FROM Portal
            WHERE {column} = ?
            ORDER BY id
            """,
            (world_id,),
        ).fetchall()

    groups: dict[
        tuple[int, int, int],
        list[dict[str, object]],
    ] = {}

    for row in rows:
        if normalized_side == "a":
            key = (
                int(row["worldIdA"]),
                int(row["xA"]),
                int(row["yA"]),
            )
        else:
            key = (
                int(row["worldIdB"]),
                int(row["xB"]),
                int(row["yB"]),
            )

        groups.setdefault(key, []).append(
            {
                "id": int(row["id"]),
                "world_id_a": int(row["worldIdA"]),
                "x_a": int(row["xA"]),
                "y_a": int(row["yA"]),
                "world_id_b": int(row["worldIdB"]),
                "x_b": int(row["xB"]),
                "y_b": int(row["yB"]),
                "data": bytes(row["data"] or b""),
            }
        )

    result = []

    for key, items in sorted(groups.items()):
        payloads = [
            item["data"][29:]
            for item in items
            if len(item["data"]) >= 29
        ]
        prefix_length = _common_prefix_length(payloads)
        suffix_length = _common_suffix_length(payloads)

        first_payload = (
            payloads[0]
            if payloads
            else b""
        )
        position_candidate = (
            _opening_a_position_candidate(
                items[0]["data"]
            )
            if normalized_side == "a"
            else None
        )

        result.append(
            {
                "side": normalized_side,
                "world_id": key[0],
                "cell": [key[1], key[2]],
                "portals": [
                    {
                        "id": item["id"],
                        "other_world": (
                            item["world_id_b"]
                            if normalized_side == "a"
                            else item["world_id_a"]
                        ),
                        "other_cell": (
                            [item["x_b"], item["y_b"]]
                            if normalized_side == "a"
                            else [item["x_a"], item["y_a"]]
                        ),
                        "blob_size": len(item["data"]),
                    }
                    for item in items
                ],
                "count": len(items),
                "payload_common_prefix_bytes": prefix_length,
                "payload_common_prefix_hex": (
                    first_payload[:prefix_length].hex()
                ),
                "payload_common_suffix_bytes": suffix_length,
                "payload_common_suffix_hex": (
                    first_payload[
                        len(first_payload) - suffix_length:
                    ].hex()
                    if suffix_length
                    else ""
                ),
                "opening_a_position_candidate": (
                    None
                    if position_candidate is None
                    else [
                        round(value, 6)
                        for value in position_candidate
                    ]
                ),
            }
        )

    return result
