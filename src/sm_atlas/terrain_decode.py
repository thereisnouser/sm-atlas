from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from struct import unpack_from

from .database import SaveDatabase
from .formats.lz4 import Lz4BlockError, decompress_block

CHUNKS_PER_CELL_XY = 4
CHUNK_INDEX_MIN_Z = -125
CHUNK_INDEX_MAX_Z = 63

HEADER_MAGIC = b"\x0c\x00\x01"
ID_OFFSET = 3
COORDINATE_OFFSET = 19
VOXEL_PAYLOAD_OFFSET = 31
VOXELS_PER_CHUNK_AXIS = 17
VOXELS_PER_CHUNK = VOXELS_PER_CHUNK_AXIS ** 3
EXPECTED_RECORD_SIZE = VOXEL_PAYLOAD_OFFSET + VOXELS_PER_CHUNK


@dataclass(frozen=True)
class DecodedVoxelRecord:
    record_id: int
    cell_x: int
    cell_y: int
    chunk_x: int
    chunk_y: int
    chunk_z: int
    compressed_size: int
    decompressed_size: int
    header_hex: str
    voxel_payload_size: int
    exact_voxel_payload: bool
    material_counts: dict[int, int]
    zero_density_voxels: int
    nonzero_density_voxels: int

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
            "compressed_size": self.compressed_size,
            "decompressed_size": self.decompressed_size,
            "header_hex": self.header_hex,
            "voxel_payload_size": self.voxel_payload_size,
            "exact_voxel_payload": self.exact_voxel_payload,
            "material_counts": self.material_counts,
            "zero_density_voxels": self.zero_density_voxels,
            "nonzero_density_voxels": self.nonzero_density_voxels,
        }


def _matches_cell(chunk_value: int, cell_value: int) -> bool:
    minimum = cell_value * CHUNKS_PER_CELL_XY
    maximum = minimum + CHUNKS_PER_CELL_XY - 1
    return minimum <= chunk_value <= maximum


def decode_voxel_record(
    *,
    record_id: int,
    cell_x: int,
    cell_y: int,
    blob: bytes,
) -> tuple[DecodedVoxelRecord | None, str | None]:
    try:
        data = decompress_block(
            blob,
            max_output_size=64 * 1024,
        )
    except Lz4BlockError as exc:
        return None, f"lz4:{exc}"

    if len(data) < VOXEL_PAYLOAD_OFFSET:
        return None, "short"

    if data[:3] != HEADER_MAGIC:
        return None, "magic"

    decoded_id = unpack_from(">I", data, ID_OFFSET)[0]
    if decoded_id != record_id:
        return None, "id"

    chunk_z, chunk_y, chunk_x = unpack_from(
        ">iii",
        data,
        COORDINATE_OFFSET,
    )

    if not _matches_cell(chunk_x, cell_x):
        return None, "cell_x"
    if not _matches_cell(chunk_y, cell_y):
        return None, "cell_y"
    if not CHUNK_INDEX_MIN_Z <= chunk_z <= CHUNK_INDEX_MAX_Z:
        return None, "chunk_z"

    payload = data[VOXEL_PAYLOAD_OFFSET:]
    exact_voxel_payload = len(payload) == VOXELS_PER_CHUNK

    material_counts: Counter[int] = Counter()
    zero_density_voxels = 0
    nonzero_density_voxels = 0

    if exact_voxel_payload:
        for voxel in payload:
            material = (voxel & 0b11000000) >> 6
            density = voxel & 0b00111111

            material_counts[material] += 1
            if density == 0:
                zero_density_voxels += 1
            else:
                nonzero_density_voxels += 1

    return (
        DecodedVoxelRecord(
            record_id=record_id,
            cell_x=cell_x,
            cell_y=cell_y,
            chunk_x=chunk_x,
            chunk_y=chunk_y,
            chunk_z=chunk_z,
            compressed_size=len(blob),
            decompressed_size=len(data),
            header_hex=data[:VOXEL_PAYLOAD_OFFSET].hex(),
            voxel_payload_size=len(payload),
            exact_voxel_payload=exact_voxel_payload,
            material_counts=dict(sorted(material_counts.items())),
            zero_density_voxels=zero_density_voxels,
            nonzero_density_voxels=nonzero_density_voxels,
        ),
        None,
    )


def probe_decompressed_voxel_terrain(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
    examples: int = 10,
) -> dict[str, object]:
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    if not 0 <= examples <= 100:
        raise ValueError("examples must be between 0 and 100")

    with database.connect() as connection:
        if "VoxelTerrain" not in database._tables(connection):
            rows = []
        else:
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

    decoded: list[DecodedVoxelRecord] = []
    failures: Counter[str] = Counter()
    size_histogram: Counter[int] = Counter()
    payload_size_histogram: Counter[int] = Counter()
    coordinates: Counter[tuple[int, int, int]] = Counter()

    exact_payload_records = 0
    total_zero_density = 0
    total_nonzero_density = 0
    material_counts: Counter[int] = Counter()

    for row in rows:
        blob = row["data"]
        if not isinstance(blob, bytes):
            failures["not_blob"] += 1
            continue

        record, failure = decode_voxel_record(
            record_id=int(row["id"]),
            cell_x=int(row["x"]),
            cell_y=int(row["y"]),
            blob=blob,
        )

        if record is None:
            failures[failure or "unknown"] += 1
            continue

        decoded.append(record)
        coordinates[
            (record.chunk_x, record.chunk_y, record.chunk_z)
        ] += 1
        size_histogram[record.decompressed_size] += 1
        payload_size_histogram[record.voxel_payload_size] += 1

        if record.exact_voxel_payload:
            exact_payload_records += 1
            total_zero_density += record.zero_density_voxels
            total_nonzero_density += record.nonzero_density_voxels
            material_counts.update(record.material_counts)

    duplicates = sum(
        count - 1
        for count in coordinates.values()
        if count > 1
    )

    if decoded:
        bounds: dict[str, int] | None = {
            "min_x": min(record.chunk_x for record in decoded),
            "max_x": max(record.chunk_x for record in decoded),
            "min_y": min(record.chunk_y for record in decoded),
            "max_y": max(record.chunk_y for record in decoded),
            "min_z": min(record.chunk_z for record in decoded),
            "max_z": max(record.chunk_z for record in decoded),
        }
    else:
        bounds = None

    return {
        "world_id": world_id,
        "scanned_records": len(rows),
        "decoded_records": len(decoded),
        "decode_ratio": (
            round(len(decoded) / len(rows), 4)
            if rows
            else 0.0
        ),
        "failures": dict(failures.most_common()),
        "decompressed_size_histogram": {
            str(size): count
            for size, count in sorted(size_histogram.items())
        },
        "payload_size_histogram": {
            str(size): count
            for size, count in sorted(payload_size_histogram.items())
        },
        "expected_record_size": EXPECTED_RECORD_SIZE,
        "expected_voxel_payload_size": VOXELS_PER_CHUNK,
        "exact_voxel_payload_records": exact_payload_records,
        "unique_chunk_coordinates": len(coordinates),
        "duplicate_coordinate_records": duplicates,
        "chunk_bounds": bounds,
        "voxel_totals": {
            "zero_density": total_zero_density,
            "nonzero_density": total_nonzero_density,
            "materials": dict(sorted(material_counts.items())),
        },
        "examples": [
            record.to_dict()
            for record in decoded[:examples]
        ],
    }
