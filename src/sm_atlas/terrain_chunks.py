from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from struct import unpack_from

from .database import SaveDatabase

CHUNKS_PER_CELL_XY = 4
CHUNK_INDEX_MIN_Z = -125
CHUNK_INDEX_MAX_Z = 63
VOXEL_MARKER = b"\x0c\x00\x01"
COORDINATE_RELATIVE_OFFSET = 16
PAYLOAD_RELATIVE_OFFSET = 28


@dataclass(frozen=True)
class VoxelChunkRecord:
    record_id: int
    cell_x: int
    cell_y: int
    chunk_x: int
    chunk_y: int
    chunk_z: int
    marker_offset: int
    id_offset: int
    prefix_hex: str
    blob_size: int
    payload_offset: int
    payload_size: int
    payload_prefix_hex: str

    @property
    def coordinate(self) -> tuple[int, int, int]:
        return (self.chunk_x, self.chunk_y, self.chunk_z)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.record_id,
            "cell": {
                "x": self.cell_x,
                "y": self.cell_y,
            },
            "chunk": {
                "x": self.chunk_x,
                "y": self.chunk_y,
                "z": self.chunk_z,
            },
            "marker_offset": self.marker_offset,
            "id_offset": self.id_offset,
            "prefix_hex": self.prefix_hex,
            "blob_size": self.blob_size,
            "payload_offset": self.payload_offset,
            "payload_size": self.payload_size,
            "payload_prefix_hex": self.payload_prefix_hex,
        }


def _matches_cell(chunk_value: int, cell_value: int) -> bool:
    minimum = cell_value * CHUNKS_PER_CELL_XY
    maximum = minimum + CHUNKS_PER_CELL_XY - 1
    return minimum <= chunk_value <= maximum


def parse_voxel_chunk_record(
    *,
    record_id: int,
    cell_x: int,
    cell_y: int,
    blob: bytes,
) -> VoxelChunkRecord | None:
    marker_offset = blob.find(VOXEL_MARKER, 0, 16)
    if marker_offset < 0:
        return None

    record_id_bytes = record_id.to_bytes(4, "big", signed=False)
    id_offset = blob.find(
        record_id_bytes,
        marker_offset + len(VOXEL_MARKER),
        32,
    )
    if id_offset < 0:
        return None

    coordinate_offset = id_offset + COORDINATE_RELATIVE_OFFSET
    if coordinate_offset + 12 > len(blob):
        return None

    chunk_z, chunk_y, chunk_x = unpack_from(
        ">iii",
        blob,
        coordinate_offset,
    )

    if not _matches_cell(chunk_x, cell_x):
        return None
    if not _matches_cell(chunk_y, cell_y):
        return None
    if not CHUNK_INDEX_MIN_Z <= chunk_z <= CHUNK_INDEX_MAX_Z:
        return None

    payload_offset = id_offset + PAYLOAD_RELATIVE_OFFSET
    if payload_offset > len(blob):
        return None

    return VoxelChunkRecord(
        record_id=record_id,
        cell_x=cell_x,
        cell_y=cell_y,
        chunk_x=chunk_x,
        chunk_y=chunk_y,
        chunk_z=chunk_z,
        marker_offset=marker_offset,
        id_offset=id_offset,
        prefix_hex=blob[:marker_offset].hex(),
        blob_size=len(blob),
        payload_offset=payload_offset,
        payload_size=len(blob) - payload_offset,
        payload_prefix_hex=blob[
            payload_offset:payload_offset + 16
        ].hex(),
    )


def decode_voxel_chunks(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
) -> list[VoxelChunkRecord]:
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")

    with database.connect() as connection:
        if "VoxelTerrain" not in database._tables(connection):
            return []

        rows = connection.execute(
            """
            SELECT id, x, y, data
            FROM VoxelTerrain
            WHERE worldId = ?
            ORDER BY id
            LIMIT ?
            """,
            (world_id, limit),
        ).fetchall()

    decoded: list[VoxelChunkRecord] = []

    for row in rows:
        blob = row["data"]
        if not isinstance(blob, bytes):
            continue

        record = parse_voxel_chunk_record(
            record_id=int(row["id"]),
            cell_x=int(row["x"]),
            cell_y=int(row["y"]),
            blob=blob,
        )
        if record is not None:
            decoded.append(record)

    return decoded


def summarize_voxel_chunks(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
    examples: int = 25,
) -> dict[str, object]:
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    if not 0 <= examples <= 200:
        raise ValueError("examples must be between 0 and 200")

    with database.connect() as connection:
        if "VoxelTerrain" not in database._tables(connection):
            total_rows = 0
        else:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM (
                    SELECT id
                    FROM VoxelTerrain
                    WHERE worldId = ?
                    ORDER BY id
                    LIMIT ?
                )
                """,
                (world_id, limit),
            ).fetchone()
            total_rows = int(row["count"])

    decoded = decode_voxel_chunks(
        database,
        world_id=world_id,
        limit=limit,
    )

    coordinate_counts = Counter(record.coordinate for record in decoded)
    z_histogram = Counter(record.chunk_z for record in decoded)
    prefix_signatures = Counter(record.prefix_hex for record in decoded)
    payload_prefixes = Counter(
        record.payload_prefix_hex[:4]
        for record in decoded
        if record.payload_prefix_hex
    )

    duplicate_coordinates = sum(
        1
        for count in coordinate_counts.values()
        if count > 1
    )
    duplicate_coordinate_records = sum(
        count - 1
        for count in coordinate_counts.values()
        if count > 1
    )

    if decoded:
        chunk_bounds: dict[str, int] | None = {
            "min_x": min(record.chunk_x for record in decoded),
            "max_x": max(record.chunk_x for record in decoded),
            "min_y": min(record.chunk_y for record in decoded),
            "max_y": max(record.chunk_y for record in decoded),
            "min_z": min(record.chunk_z for record in decoded),
            "max_z": max(record.chunk_z for record in decoded),
        }
    else:
        chunk_bounds = None

    return {
        "world_id": world_id,
        "scanned_records": total_rows,
        "decoded_records": len(decoded),
        "unresolved_records": total_rows - len(decoded),
        "decode_ratio": (
            round(len(decoded) / total_rows, 4)
            if total_rows
            else 0.0
        ),
        "unique_chunk_coordinates": len(coordinate_counts),
        "duplicate_coordinate_records": duplicate_coordinate_records,
        "duplicate_coordinates": duplicate_coordinates,
        "chunk_bounds": chunk_bounds,
        "z_histogram": {
            str(z): count
            for z, count in sorted(z_histogram.items())
        },
        "prefix_signatures": dict(prefix_signatures.most_common()),
        "payload_prefixes": dict(payload_prefixes.most_common(30)),
        "examples": [
            record.to_dict()
            for record in decoded[:examples]
        ],
    }
