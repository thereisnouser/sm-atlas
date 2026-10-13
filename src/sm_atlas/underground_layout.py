from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .database import SaveDatabase
from .underground_features import (
    CELL_SIZE_METERS,
    UndergroundPiece,
    extract_caves,
    extract_pockets,
)
from .underground_pockets import (
    reconstruct_logical_pockets,
    rotated_source_offset,
    summarize_logical_pockets,
)
from .underground_tile_catalog import _tile_family, _tile_name
from .underground_tile_metadata import UNDERGROUND_TILE_METADATA
from .underground_tunnels import _load_terrain_table

_DIMENSIONS_RE = re.compile(r"_(\d+)x(\d+)x(\d+)\.tile$", re.IGNORECASE)


@dataclass(frozen=True)
class LogicalStructure:
    structure_id: int
    tile_uuid: str
    name: str
    family: str
    rotation: int
    z: float
    fragments: tuple[UndergroundPiece, ...]
    expected_fragments: int | None
    expected_width: float | None
    expected_depth: float | None
    expected_height: float | None
    source_aware: bool = False
    source_complete: bool | None = None
    source_overlap_cells: int | None = None

    @property
    def min_x(self) -> float:
        return min(piece.x for piece in self.fragments)

    @property
    def max_x(self) -> float:
        return max(piece.max_x for piece in self.fragments)

    @property
    def min_y(self) -> float:
        return min(piece.y for piece in self.fragments)

    @property
    def max_y(self) -> float:
        return max(piece.max_y for piece in self.fragments)

    @property
    def min_z(self) -> float:
        return min(piece.z for piece in self.fragments)

    @property
    def max_z(self) -> float:
        return max(piece.max_z for piece in self.fragments)

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def depth(self) -> float:
        return self.max_y - self.min_y

    @property
    def height(self) -> float:
        return self.max_z - self.min_z

    @property
    def complete(self) -> bool | None:
        if self.expected_fragments is None:
            return None
        if self.source_aware:
            return bool(
                self.source_complete
                and self.source_overlap_cells == 0
                and self.dimensions_match
            )
        return len(self.fragments) == self.expected_fragments

    @property
    def dimensions_match(self) -> bool | None:
        if (
            self.expected_width is None
            or self.expected_depth is None
            or self.expected_height is None
        ):
            return None
        return (
            abs(self.width - self.expected_width) < 1e-6
            and abs(self.depth - self.expected_depth) < 1e-6
            and abs(self.height - self.expected_height) < 1e-6
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.structure_id,
            "uuid": self.tile_uuid,
            "name": self.name,
            "family": self.family,
            "rotation": self.rotation,
            "fragments": len(self.fragments),
            "expected_fragments": self.expected_fragments,
            "complete": self.complete,
            "source_aware": self.source_aware,
            "source_complete": self.source_complete,
            "source_overlap_cells": self.source_overlap_cells,
            "bounds": {
                "min_x": self.min_x,
                "max_x": self.max_x,
                "min_y": self.min_y,
                "max_y": self.max_y,
                "min_z": self.min_z,
                "max_z": self.max_z,
            },
            "size": {
                "width": self.width,
                "depth": self.depth,
                "height": self.height,
            },
            "expected_size": (
                None
                if self.expected_width is None
                else {
                    "width": self.expected_width,
                    "depth": self.expected_depth,
                    "height": self.expected_height,
                }
            ),
            "dimensions_match": self.dimensions_match,
            "source_cells": sorted(
                {
                    (piece.source_x, piece.source_y)
                    for piece in self.fragments
                }
            ),
        }


def _dimensions_from_name(name: str) -> tuple[int, int, int] | None:
    match = _DIMENSIONS_RE.search(name)
    if match is None:
        return None
    return tuple(int(value) for value in match.groups())


def _expected_world_size(
    dimensions: tuple[int, int, int],
    rotation: int,
) -> tuple[float, float, float]:
    width_chunks, depth_chunks, height_chunks = dimensions

    if rotation & 1:
        width_chunks, depth_chunks = depth_chunks, width_chunks

    return (
        width_chunks * 16.0,
        depth_chunks * 16.0,
        height_chunks * 16.0,
    )


def _expected_fragment_count(
    dimensions: tuple[int, int, int],
) -> int:
    width_chunks, depth_chunks, _ = dimensions

    width_cells = (width_chunks + 3) // 4
    depth_cells = (depth_chunks + 3) // 4
    return width_cells * depth_cells


def _face_adjacent(
    left: UndergroundPiece,
    right: UndergroundPiece,
) -> bool:
    if abs(left.z - right.z) > 1e-6:
        return False

    dx = abs(left.cell_x - right.cell_x)
    dy = abs(left.cell_y - right.cell_y)
    return (dx == 1 and dy == 0) or (dx == 0 and dy == 1)


def _cave_source_key(
    piece: UndergroundPiece,
    dimensions: tuple[int, int, int],
) -> tuple[str, int, float, int, int] | None:
    """Reconstruct the recorded tile placement from its 4-chunk source cell."""
    width, depth, _ = dimensions
    if (
        width < 4 or depth < 4 or width % 4 or depth % 4
        or piece.source_x % 4 or piece.source_y % 4
        or piece.source_x < 0 or piece.source_y < 0
        or piece.source_x + 4 > width or piece.source_y + 4 > depth
        or piece.width != 64.0 or piece.depth != 64.0
        or piece.x != piece.cell_x * 64.0
        or piece.y != piece.cell_y * 64.0
        or piece.rotation not in range(4)
    ):
        return None
    dx, dy = rotated_source_offset(
        source_x=piece.source_x,
        source_y=piece.source_y,
        source_width=4,
        source_depth=4,
        tile_width=width,
        tile_depth=depth,
        rotation=piece.rotation,
    )
    return (
        piece.tile_uuid or "", piece.rotation, piece.z,
        piece.cell_x * 4 - dx, piece.cell_y * 4 - dy,
    )


def reconstruct_logical_structures(
    cave_fragments: list[UndergroundPiece],
) -> list[LogicalStructure]:
    """Group source-backed known caves; fall back to adjacency when unknown.

    Matching neighboring UUIDs do not imply matching source origins.
    Neither grouping method establishes navigability or actual room interiors.
    """
    source_groups: dict[
        tuple[str, int, float, int, int], list[UndergroundPiece]
    ] = {}
    fallback: list[UndergroundPiece] = []
    for piece in cave_fragments:
        meta = UNDERGROUND_TILE_METADATA.get(piece.tile_uuid or "")
        name = _tile_name(str(meta["path"])) if meta else ""
        dims = _dimensions_from_name(name) if name else None
        key = _cave_source_key(piece, dims) if dims else None
        if key is None:
            fallback.append(piece)
        else:
            source_groups.setdefault(key, []).append(piece)

    # Conservative legacy grouping only for cells without usable source IDs.
    fallback_groups: list[list[UndergroundPiece]] = []
    remaining = set(range(len(fallback)))
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        stack = [start]
        component: list[int] = []
        while stack:
            index = stack.pop()
            component.append(index)
            piece = fallback[index]
            for other_index in list(remaining):
                other = fallback[other_index]
                if (
                    piece.tile_uuid != other.tile_uuid
                    or (piece.tile_uuid is None
                        and piece.tile_index != other.tile_index)
                    or piece.rotation != other.rotation
                    or not _face_adjacent(piece, other)
                ):
                    continue
                remaining.remove(other_index)
                stack.append(other_index)
        fallback_groups.append([fallback[i] for i in component])

    groups = [(parts, True) for parts in source_groups.values()]
    groups.extend((parts, False) for parts in fallback_groups)
    groups.sort(
        key=lambda item: (
            min(piece.z for piece in item[0]),
            min(piece.y for piece in item[0]),
            min(piece.x for piece in item[0]),
            item[0][0].tile_uuid or "",
            item[0][0].tile_index,
        )
    )

    structures: list[LogicalStructure] = []
    for structure_id, (group, source_aware) in enumerate(groups, start=1):
        uuid = group[0].tile_uuid or ""
        meta = UNDERGROUND_TILE_METADATA.get(uuid)
        path = str(meta["path"]) if meta is not None else ""
        name = _tile_name(path) if path else "<unknown>"
        family = _tile_family(path) if path else "unknown"
        dimensions = _dimensions_from_name(name)
        expected_fragments = None
        expected_width = expected_depth = expected_height = None
        source_complete = None
        source_overlap_cells = None
        if dimensions is not None:
            expected_fragments = _expected_fragment_count(dimensions)
            expected_width, expected_depth, expected_height = (
                _expected_world_size(dimensions, group[0].rotation)
            )
            if source_aware:
                sources = {(p.source_x, p.source_y) for p in group}
                source_overlap_cells = len(group) - len(sources)
                source_complete = (
                    len(sources) == expected_fragments
                    and source_overlap_cells == 0
                )
        structures.append(
            LogicalStructure(
                structure_id=structure_id,
                tile_uuid=uuid,
                name=name,
                family=family,
                rotation=group[0].rotation,
                z=group[0].z,
                fragments=tuple(group),
                expected_fragments=expected_fragments,
                expected_width=expected_width,
                expected_depth=expected_depth,
                expected_height=expected_height,
                source_aware=source_aware,
                source_complete=source_complete,
                source_overlap_cells=source_overlap_cells,
            )
        )
    return structures


def _validate_pocket_dimensions(
    pieces: list[UndergroundPiece],
) -> dict[str, object]:
    checked = 0
    matched = 0
    mismatches: list[dict[str, object]] = []

    for piece in pieces:
        uuid = piece.tile_uuid or ""
        meta = UNDERGROUND_TILE_METADATA.get(uuid)
        if meta is None:
            continue

        path = str(meta["path"])
        name = _tile_name(path)
        dimensions = _dimensions_from_name(name)
        if dimensions is None:
            continue

        expected_width, expected_depth, expected_height = _expected_world_size(
            dimensions,
            piece.rotation,
        )
        checked += 1

        ok = (
            abs(piece.width - expected_width) < 1e-6
            and abs(piece.depth - expected_depth) < 1e-6
            and abs(piece.height - expected_height) < 1e-6
        )

        if ok:
            matched += 1
            continue

        if len(mismatches) < 20:
            mismatches.append(
                {
                    "tile_index": piece.tile_index,
                    "name": name,
                    "rotation": piece.rotation,
                    "actual": {
                        "width": piece.width,
                        "depth": piece.depth,
                        "height": piece.height,
                    },
                    "expected": {
                        "width": expected_width,
                        "depth": expected_depth,
                        "height": expected_height,
                    },
                }
            )

    return {
        "checked": checked,
        "matched": matched,
        "mismatched": checked - matched,
        "match_ratio": (
            round(matched / checked, 6)
            if checked
            else None
        ),
        "examples": mismatches,
    }


def summarize_underground_layout(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
) -> dict[str, object]:
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")

    row_id, value = _load_terrain_table(
        database,
        world_id=world_id,
        limit=limit,
    )

    caves = extract_caves(value)
    pockets = extract_pockets(value)
    structures = reconstruct_logical_structures(caves)
    logical_pockets = reconstruct_logical_pockets(
        pockets,
        _dimensions_from_name,
    )

    structure_families = Counter(
        structure.family
        for structure in structures
    )
    complete = sum(
        structure.complete is True
        for structure in structures
    )
    dimensions_match = sum(
        structure.dimensions_match is True
        for structure in structures
    )

    return {
        "world_id": world_id,
        "row_id": row_id,
        "cave_fragments": len(caves),
        "logical_structures": len(structures),
        "structure_families": dict(structure_families.most_common()),
        "complete_structures": complete,
        "dimension_matched_structures": dimensions_match,
        "structures": [
            structure.to_dict()
            for structure in structures
        ],
        "pocket_reconstruction": summarize_logical_pockets(
            logical_pockets,
            len(pockets),
        ),
    }