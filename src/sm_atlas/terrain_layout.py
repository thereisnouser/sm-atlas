from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import permutations
from struct import unpack_from

from .database import SaveDatabase

DEFAULT_FACTORS = (1, 2, 4, 8)
DEFAULT_MIN_RELATIVE_OFFSET = 8
DEFAULT_MAX_RELATIVE_OFFSET = 64
DEFAULT_Z_LIMIT = 128
AXIS_ORDERS = tuple("".join(order) for order in permutations("xyz"))


@dataclass(frozen=True)
class LayoutScore:
    endian: str
    axis_order: str
    factor: int
    relative_offset: int
    exact_xy_matches: int
    plausible_z_matches: int
    marker_1_matches: int
    marker_2_matches: int
    z_min: int | None
    z_max: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "endian": self.endian,
            "axis_order": self.axis_order,
            "factor": self.factor,
            "relative_offset": self.relative_offset,
            "exact_xy_matches": self.exact_xy_matches,
            "plausible_z_matches": self.plausible_z_matches,
            "marker_1_matches": self.marker_1_matches,
            "marker_2_matches": self.marker_2_matches,
            "z_range": (
                {"min": self.z_min, "max": self.z_max}
                if self.z_min is not None and self.z_max is not None
                else None
            ),
        }


def _range_for_cell(cell: int, factor: int) -> tuple[int, int]:
    start = cell * factor
    return start, start + factor - 1


def _matches_cell(
    value: int,
    cell: int,
    factor: int,
) -> bool:
    minimum, maximum = _range_for_cell(cell, factor)
    return minimum <= value <= maximum


def _score_layout(
    records: list[tuple[int, int, int, bytes, int, int]],
    *,
    endian: str,
    axis_order: str,
    factor: int,
    relative_offset: int,
    z_limit: int,
) -> LayoutScore:
    exact_xy_matches = 0
    plausible_z_matches = 0
    marker_1_matches = 0
    marker_2_matches = 0
    z_values: list[int] = []

    format_string = f"{endian}iii"

    for _, cell_x, cell_y, blob, id_offset, marker_offset in records:
        offset = id_offset + relative_offset
        if offset + 12 > len(blob):
            continue

        raw_values = unpack_from(format_string, blob, offset)
        values = dict(zip(axis_order, raw_values))

        x = values["x"]
        y = values["y"]
        z = values["z"]

        x_matches = _matches_cell(x, cell_x, factor)
        y_matches = _matches_cell(y, cell_y, factor)

        if not (x_matches and y_matches):
            continue

        exact_xy_matches += 1
        z_values.append(z)

        if marker_offset == 1:
            marker_1_matches += 1
        elif marker_offset == 2:
            marker_2_matches += 1

        if -z_limit <= z <= z_limit:
            plausible_z_matches += 1

    return LayoutScore(
        endian="big" if endian == ">" else "little",
        axis_order=axis_order,
        factor=factor,
        relative_offset=relative_offset,
        exact_xy_matches=exact_xy_matches,
        plausible_z_matches=plausible_z_matches,
        marker_1_matches=marker_1_matches,
        marker_2_matches=marker_2_matches,
        z_min=min(z_values) if z_values else None,
        z_max=max(z_values) if z_values else None,
    )


def scan_voxel_terrain_layout(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 1000,
    min_relative_offset: int = DEFAULT_MIN_RELATIVE_OFFSET,
    max_relative_offset: int = DEFAULT_MAX_RELATIVE_OFFSET,
    top: int = 25,
    z_limit: int = DEFAULT_Z_LIMIT,
) -> dict[str, object]:
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    if not 0 <= min_relative_offset <= max_relative_offset <= 256:
        raise ValueError(
            "relative offset range must satisfy 0 <= min <= max <= 256"
        )
    if not 1 <= top <= 100:
        raise ValueError("top must be between 1 and 100")
    if not 1 <= z_limit <= 100000:
        raise ValueError("z_limit must be between 1 and 100000")

    with database.connect() as connection:
        if "VoxelTerrain" not in database._tables(connection):
            return {
                "world_id": world_id,
                "scanned_records": 0,
                "records_with_id": 0,
                "top_layouts": [],
                "big_zyx_factor4_offsets": [],
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

    records: list[tuple[int, int, int, bytes, int, int]] = []

    for row in rows:
        blob = row["data"]
        if not isinstance(blob, bytes):
            continue

        record_id = int(row["id"])
        record_id_bytes = record_id.to_bytes(4, "big", signed=False)
        id_offset = blob.find(record_id_bytes, 0, 32)

        if id_offset < 0:
            continue

        marker_offset = blob.find(b"\x0c\x00\x01", 0, 16)
        if marker_offset < 0:
            marker_offset = -1

        records.append(
            (
                record_id,
                int(row["x"]),
                int(row["y"]),
                blob,
                id_offset,
                marker_offset,
            )
        )

    scores: list[LayoutScore] = []

    for endian in (">", "<"):
        for axis_order in AXIS_ORDERS:
            for factor in DEFAULT_FACTORS:
                for relative_offset in range(
                    min_relative_offset,
                    max_relative_offset + 1,
                ):
                    score = _score_layout(
                        records,
                        endian=endian,
                        axis_order=axis_order,
                        factor=factor,
                        relative_offset=relative_offset,
                        z_limit=z_limit,
                    )
                    if score.exact_xy_matches:
                        scores.append(score)

    scores.sort(
        key=lambda score: (
            score.plausible_z_matches,
            score.exact_xy_matches,
            -score.relative_offset,
        ),
        reverse=True,
    )

    zyx_scores = [
        score
        for score in scores
        if score.endian == "big"
        and score.axis_order == "zyx"
        and score.factor == 4
    ]
    zyx_scores.sort(
        key=lambda score: (
            score.plausible_z_matches,
            score.exact_xy_matches,
            -score.relative_offset,
        ),
        reverse=True,
    )

    marker_histogram: Counter[int] = Counter(
        marker_offset
        for _, _, _, _, _, marker_offset in records
        if marker_offset >= 0
    )

    return {
        "world_id": world_id,
        "scanned_records": len(rows),
        "records_with_id": len(records),
        "relative_offset_range": {
            "min": min_relative_offset,
            "max": max_relative_offset,
        },
        "z_limit": z_limit,
        "marker_offsets": {
            str(offset): count
            for offset, count in sorted(marker_histogram.items())
        },
        "top_layouts": [
            score.to_dict()
            for score in scores[:top]
        ],
        "big_zyx_factor4_offsets": [
            score.to_dict()
            for score in zyx_scores[:top]
        ],
    }
