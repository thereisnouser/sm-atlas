from __future__ import annotations

from collections import Counter

from .database import SaveDatabase
from .terrain_decode import (
    DecodedVoxelRecord,
    decode_voxel_records,
)


def decode_voxel_chunks(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
) -> list[DecodedVoxelRecord]:
    records, _, _ = decode_voxel_records(
        database,
        world_id=world_id,
        limit=limit,
    )
    return records


def summarize_voxel_chunks(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
    examples: int = 25,
) -> dict[str, object]:
    if not 0 <= examples <= 200:
        raise ValueError("examples must be between 0 and 200")

    decoded, failures, scanned_records = decode_voxel_records(
        database,
        world_id=world_id,
        limit=limit,
    )

    coordinate_counts = Counter(record.coordinate for record in decoded)
    z_histogram = Counter(record.chunk_z for record in decoded)
    payload_size_histogram = Counter(
        record.voxel_payload_size
        for record in decoded
    )
    payload_prefixes = Counter(
        record.payload[:4].hex()
        for record in decoded
        if record.payload
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

    return {
        "world_id": world_id,
        "scanned_records": scanned_records,
        "decoded_records": len(decoded),
        "unresolved_records": scanned_records - len(decoded),
        "decode_ratio": (
            round(len(decoded) / scanned_records, 4)
            if scanned_records
            else 0.0
        ),
        "failures": dict(failures.most_common()),
        "unique_chunk_coordinates": len(coordinate_counts),
        "duplicate_coordinate_records": duplicate_coordinate_records,
        "duplicate_coordinates": duplicate_coordinates,
        "chunk_bounds": chunk_bounds,
        "z_histogram": {
            str(z): count
            for z, count in sorted(z_histogram.items())
        },
        "payload_size_histogram": {
            str(size): count
            for size, count in sorted(payload_size_histogram.items())
        },
        "payload_prefixes": dict(payload_prefixes.most_common(30)),
        "examples": [
            record.to_dict()
            for record in decoded[:examples]
        ],
    }
