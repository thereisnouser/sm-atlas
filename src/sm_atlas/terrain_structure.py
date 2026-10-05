from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from struct import unpack_from

from .database import SaveDatabase

VOXEL_TERRAIN_MARKER = b"\x0c\x00\x01"
CHUNKS_PER_CELL_XY = 4
CHUNK_Z_MIN = -125
CHUNK_Z_MAX = 63


@dataclass(frozen=True)
class ChunkCoordinateCandidate:
    x: int
    y: int
    z: int
    exact_cell_match: bool
    boundary_cell_match: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "exact_cell_match": self.exact_cell_match,
            "boundary_cell_match": self.boundary_cell_match,
        }


@dataclass(frozen=True)
class StructureRecord:
    record_id: int
    cell_x: int
    cell_y: int
    blob_size: int
    marker_offset: int | None
    id_offset: int | None
    prefix_hex: str
    has_minus_one_sentinel: bool
    candidate: ChunkCoordinateCandidate | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.record_id,
            "cell_x": self.cell_x,
            "cell_y": self.cell_y,
            "blob_size": self.blob_size,
            "marker_offset": self.marker_offset,
            "id_offset": self.id_offset,
            "prefix_hex": self.prefix_hex,
            "has_minus_one_sentinel": self.has_minus_one_sentinel,
            "candidate_xyz": (
                self.candidate.to_dict()
                if self.candidate is not None
                else None
            ),
        }


def _cell_range(cell: int) -> tuple[int, int]:
    start = cell * CHUNKS_PER_CELL_XY
    return start, start + CHUNKS_PER_CELL_XY - 1


def _candidate_xyz(
    blob: bytes,
    *,
    id_offset: int,
    cell_x: int,
    cell_y: int,
) -> ChunkCoordinateCandidate | None:
    coordinate_offset = id_offset + 16
    if coordinate_offset + 12 > len(blob):
        return None

    x, y, z = unpack_from(">iii", blob, coordinate_offset)

    x_min, x_max = _cell_range(cell_x)
    y_min, y_max = _cell_range(cell_y)

    exact = (
        x_min <= x <= x_max
        and y_min <= y <= y_max
        and CHUNK_Z_MIN <= z <= CHUNK_Z_MAX
    )
    boundary = (
        x_min - 1 <= x <= x_max + 1
        and y_min - 1 <= y <= y_max + 1
        and CHUNK_Z_MIN <= z <= CHUNK_Z_MAX
    )

    if not boundary:
        return None

    return ChunkCoordinateCandidate(
        x=x,
        y=y,
        z=z,
        exact_cell_match=exact,
        boundary_cell_match=boundary,
    )


def analyze_structure_record(
    *,
    record_id: int,
    cell_x: int,
    cell_y: int,
    blob: bytes,
) -> StructureRecord:
    marker_offset = blob.find(VOXEL_TERRAIN_MARKER, 0, 16)
    if marker_offset < 0:
        marker_offset = None

    record_id_bytes = record_id.to_bytes(4, "big", signed=False)
    id_offset = blob.find(record_id_bytes, 0, 32)
    if id_offset < 0:
        id_offset = None

    prefix_end = marker_offset if marker_offset is not None else min(8, len(blob))
    prefix_hex = blob[:prefix_end].hex()

    has_minus_one_sentinel = False
    candidate = None

    if id_offset is not None:
        sentinel_offset = id_offset + 4
        has_minus_one_sentinel = (
            sentinel_offset + 4 <= len(blob)
            and blob[sentinel_offset:sentinel_offset + 4] == b"\xff" * 4
        )
        candidate = _candidate_xyz(
            blob,
            id_offset=id_offset,
            cell_x=cell_x,
            cell_y=cell_y,
        )

    return StructureRecord(
        record_id=record_id,
        cell_x=cell_x,
        cell_y=cell_y,
        blob_size=len(blob),
        marker_offset=marker_offset,
        id_offset=id_offset,
        prefix_hex=prefix_hex,
        has_minus_one_sentinel=has_minus_one_sentinel,
        candidate=candidate,
    )


def probe_voxel_terrain_structure(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 500,
    examples: int = 30,
) -> dict[str, object]:
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    if not 0 <= examples <= 200:
        raise ValueError("examples must be between 0 and 200")

    with database.connect() as connection:
        if "VoxelTerrain" not in database._tables(connection):
            return {
                "world_id": world_id,
                "scanned_records": 0,
                "marker_matches": 0,
                "id_matches": 0,
                "sentinel_matches": 0,
                "direct_coordinate_candidates": 0,
                "exact_cell_matches": 0,
                "boundary_cell_matches": 0,
                "marker_offsets": {},
                "id_offsets": {},
                "prefix_signatures": {},
                "candidate_z_range": None,
                "examples": [],
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

    records: list[StructureRecord] = []

    marker_offsets: Counter[int] = Counter()
    id_offsets: Counter[int] = Counter()
    prefixes: Counter[str] = Counter()
    candidate_z: list[int] = []

    marker_matches = 0
    id_matches = 0
    sentinel_matches = 0
    direct_coordinate_candidates = 0
    exact_cell_matches = 0
    boundary_cell_matches = 0

    for row in rows:
        blob = row["data"]
        if not isinstance(blob, bytes):
            continue

        record = analyze_structure_record(
            record_id=int(row["id"]),
            cell_x=int(row["x"]),
            cell_y=int(row["y"]),
            blob=blob,
        )
        records.append(record)

        if record.marker_offset is not None:
            marker_matches += 1
            marker_offsets[record.marker_offset] += 1
            prefixes[record.prefix_hex] += 1

        if record.id_offset is not None:
            id_matches += 1
            id_offsets[record.id_offset] += 1

        if record.has_minus_one_sentinel:
            sentinel_matches += 1

        if record.candidate is not None:
            direct_coordinate_candidates += 1
            candidate_z.append(record.candidate.z)

            if record.candidate.exact_cell_match:
                exact_cell_matches += 1
            if record.candidate.boundary_cell_match:
                boundary_cell_matches += 1

    candidate_records = [
        record
        for record in records
        if record.candidate is not None
    ]
    other_records = [
        record
        for record in records
        if record.candidate is None
    ]
    example_records = (candidate_records + other_records)[:examples]

    return {
        "world_id": world_id,
        "scanned_records": len(records),
        "marker_matches": marker_matches,
        "id_matches": id_matches,
        "sentinel_matches": sentinel_matches,
        "direct_coordinate_candidates": direct_coordinate_candidates,
        "exact_cell_matches": exact_cell_matches,
        "boundary_cell_matches": boundary_cell_matches,
        "marker_offsets": {
            str(offset): count
            for offset, count in sorted(marker_offsets.items())
        },
        "id_offsets": {
            str(offset): count
            for offset, count in sorted(id_offsets.items())
        },
        "prefix_signatures": dict(prefixes.most_common()),
        "candidate_z_range": (
            {
                "min": min(candidate_z),
                "max": max(candidate_z),
            }
            if candidate_z
            else None
        ),
        "examples": [
            record.to_dict()
            for record in example_records
        ],
    }
