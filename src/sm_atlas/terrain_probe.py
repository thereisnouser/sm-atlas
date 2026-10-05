from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass

from .database import SaveDatabase
from .formats.lz4 import Lz4BlockError, decompress_block_prefix

VOXELS_PER_CHUNK = 17 * 17 * 17


@dataclass(frozen=True)
class Lz4Candidate:
    offset: int
    compressed_size: int
    voxel_sha256: str
    nonzero_density: int
    material_counts: dict[int, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "offset": self.offset,
            "compressed_size": self.compressed_size,
            "voxel_sha256": self.voxel_sha256,
            "nonzero_density": self.nonzero_density,
            "material_counts": self.material_counts,
        }


@dataclass(frozen=True)
class TerrainProbeRecord:
    record_id: int
    x: int
    y: int
    blob_size: int
    prefix_hex: str
    candidates: tuple[Lz4Candidate, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.record_id,
            "x": self.x,
            "y": self.y,
            "blob_size": self.blob_size,
            "prefix_hex": self.prefix_hex,
            "lz4_candidates": [
                candidate.to_dict()
                for candidate in self.candidates
            ],
        }


def _candidate_from_payload(
    blob: bytes,
    offset: int,
) -> Lz4Candidate | None:
    try:
        voxels, consumed = decompress_block_prefix(
            blob[offset:],
            expected_output_size=VOXELS_PER_CHUNK,
        )
    except Lz4BlockError:
        return None

    if len(voxels) != VOXELS_PER_CHUNK:
        return None

    materials: Counter[int] = Counter()
    nonzero_density = 0

    for voxel in voxels:
        material = (voxel & 0b11000000) >> 6
        density = voxel & 0b00111111
        materials[material] += 1
        if density != 0:
            nonzero_density += 1

    return Lz4Candidate(
        offset=offset,
        compressed_size=consumed,
        voxel_sha256=hashlib.sha256(voxels).hexdigest(),
        nonzero_density=nonzero_density,
        material_counts=dict(sorted(materials.items())),
    )


def find_lz4_candidates(
    blob: bytes,
    *,
    max_offset: int = 96,
) -> tuple[Lz4Candidate, ...]:
    candidates: list[Lz4Candidate] = []
    upper_bound = min(max_offset, max(0, len(blob) - 1))

    for offset in range(upper_bound + 1):
        candidate = _candidate_from_payload(blob, offset)
        if candidate is not None:
            candidates.append(candidate)

    return tuple(candidates)


def probe_voxel_terrain(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 100,
    max_offset: int = 96,
) -> dict[str, object]:
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    if not 0 <= max_offset <= 512:
        raise ValueError("max_offset must be between 0 and 512")

    with database.connect() as connection:
        if "VoxelTerrain" not in database._tables(connection):
            return {
                "world_id": world_id,
                "scanned_records": 0,
                "matched_records": 0,
                "offset_histogram": {},
                "records": [],
            }

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

    records: list[TerrainProbeRecord] = []
    offset_histogram: Counter[int] = Counter()
    matched_records = 0

    for row in rows:
        blob = row["data"]
        if not isinstance(blob, bytes):
            continue

        candidates = find_lz4_candidates(
            blob,
            max_offset=max_offset,
        )

        if candidates:
            matched_records += 1
            for candidate in candidates:
                offset_histogram[candidate.offset] += 1

        records.append(
            TerrainProbeRecord(
                record_id=int(row["id"]),
                x=int(row["x"]),
                y=int(row["y"]),
                blob_size=len(blob),
                prefix_hex=blob[:96].hex(),
                candidates=candidates,
            )
        )

    return {
        "world_id": world_id,
        "scanned_records": len(records),
        "matched_records": matched_records,
        "offset_histogram": {
            str(offset): count
            for offset, count in sorted(offset_histogram.items())
        },
        "records": [
            record.to_dict()
            for record in records
        ],
    }
