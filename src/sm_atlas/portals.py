from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from .database import SaveDatabase


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
    float32_be_from_29: tuple[dict[str, object], ...]


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
                float32_be_from_29=_scan_aligned_be_floats(
                    data,
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
            "float32_be_from_29": list(
                probe.float32_be_from_29
            ),
        }
        for probe in probes
    ]
