from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .underground_features import UndergroundPiece
from .underground_tile_catalog import _name_tags, _tile_family, _tile_name
from .underground_tile_metadata import UNDERGROUND_TILE_METADATA


@dataclass(frozen=True)
class LogicalPocketPlacement:
    placement_id: int
    tile_uuid: str
    tile_index: int
    name: str
    family: str
    tags: tuple[str, ...]
    rotation: int
    origin_chunk_x: int
    origin_chunk_y: int
    z: float
    dimensions: tuple[int, int, int]
    fragments: tuple[UndergroundPiece, ...]
    source_complete: bool
    source_overlap_chunks: int

    @property
    def expected_width(self) -> float:
        width, depth, _ = self.dimensions
        if self.rotation & 1:
            width, depth = depth, width
        return width * 16.0

    @property
    def expected_depth(self) -> float:
        width, depth, _ = self.dimensions
        if self.rotation & 1:
            width, depth = depth, width
        return depth * 16.0

    @property
    def expected_height(self) -> float:
        return self.dimensions[2] * 16.0

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
    def dimensions_match(self) -> bool:
        return (
            abs((self.max_x - self.min_x) - self.expected_width) < 1e-6
            and abs((self.max_y - self.min_y) - self.expected_depth) < 1e-6
            and abs((self.max_z - self.min_z) - self.expected_height) < 1e-6
        )

    @property
    def complete(self) -> bool:
        return self.source_complete and self.dimensions_match


def source_fragment_size(piece: UndergroundPiece) -> tuple[int, int]:
    world_width = int(round(piece.width / 16.0))
    world_depth = int(round(piece.depth / 16.0))
    if piece.rotation & 1:
        return world_depth, world_width
    return world_width, world_depth


def rotated_source_offset(
    *,
    source_x: int,
    source_y: int,
    source_width: int,
    source_depth: int,
    tile_width: int,
    tile_depth: int,
    rotation: int,
) -> tuple[int, int]:
    rotation &= 3

    if rotation == 1:
        return (
            tile_depth - (source_y + source_depth),
            source_x,
        )
    if rotation == 2:
        return (
            tile_width - (source_x + source_width),
            tile_depth - (source_y + source_depth),
        )
    if rotation == 3:
        return (
            source_y,
            tile_width - (source_x + source_width),
        )
    return source_x, source_y


def logical_pocket_key(
    piece: UndergroundPiece,
    dimensions: tuple[int, int, int],
) -> tuple[str, int, float, int, int]:
    tile_width, tile_depth, _ = dimensions
    source_width, source_depth = source_fragment_size(piece)
    offset_x, offset_y = rotated_source_offset(
        source_x=piece.source_x,
        source_y=piece.source_y,
        source_width=source_width,
        source_depth=source_depth,
        tile_width=tile_width,
        tile_depth=tile_depth,
        rotation=piece.rotation,
    )

    destination_x = int(round(piece.x / 16.0))
    destination_y = int(round(piece.y / 16.0))

    return (
        piece.tile_uuid or "",
        piece.rotation,
        piece.z,
        destination_x - offset_x,
        destination_y - offset_y,
    )


def source_coverage(
    fragments: list[UndergroundPiece],
    dimensions: tuple[int, int, int],
) -> tuple[bool, int]:
    tile_width, tile_depth, _ = dimensions
    expected = {
        (x, y)
        for y in range(tile_depth)
        for x in range(tile_width)
    }
    covered: set[tuple[int, int]] = set()
    overlaps = 0

    for piece in fragments:
        width, depth = source_fragment_size(piece)

        for y in range(piece.source_y, piece.source_y + depth):
            for x in range(piece.source_x, piece.source_x + width):
                point = (x, y)
                if point in covered:
                    overlaps += 1
                covered.add(point)

    return covered == expected, overlaps


def reconstruct_logical_pockets(
    pocket_fragments: list[UndergroundPiece],
    dimensions_from_name,
) -> list[LogicalPocketPlacement]:
    groups: dict[tuple[str, int, float, int, int], list[UndergroundPiece]] = {}
    dimensions_by_key: dict[
        tuple[str, int, float, int, int],
        tuple[int, int, int],
    ] = {}

    for piece in pocket_fragments:
        uuid = piece.tile_uuid or ""
        meta = UNDERGROUND_TILE_METADATA.get(uuid)
        if meta is None:
            continue

        path = str(meta["path"])
        name = _tile_name(path)
        dimensions = dimensions_from_name(name)
        if dimensions is None:
            continue

        key = logical_pocket_key(piece, dimensions)
        groups.setdefault(key, []).append(piece)
        dimensions_by_key[key] = dimensions

    ordered = sorted(
        groups.items(),
        key=lambda item: (
            item[0][2],
            item[0][4],
            item[0][3],
            item[0][0],
            item[0][1],
        ),
    )

    placements: list[LogicalPocketPlacement] = []

    for placement_id, (key, fragments) in enumerate(ordered, start=1):
        uuid, rotation, z, origin_x, origin_y = key
        dimensions = dimensions_by_key[key]
        meta = UNDERGROUND_TILE_METADATA[uuid]
        path = str(meta["path"])
        complete, overlaps = source_coverage(fragments, dimensions)

        placements.append(
            LogicalPocketPlacement(
                placement_id=placement_id,
                tile_uuid=uuid,
                tile_index=fragments[0].tile_index,
                name=_tile_name(path),
                family=_tile_family(path),
                tags=_name_tags(path),
                rotation=rotation,
                origin_chunk_x=origin_x,
                origin_chunk_y=origin_y,
                z=z,
                dimensions=dimensions,
                fragments=tuple(fragments),
                source_complete=complete,
                source_overlap_chunks=overlaps,
            )
        )

    return placements


def summarize_logical_pockets(
    placements: list[LogicalPocketPlacement],
    fragment_count: int,
) -> dict[str, object]:
    histogram = Counter(len(placement.fragments) for placement in placements)
    semantic_counts: Counter[str] = Counter()

    for placement in placements:
        semantic_counts.update(placement.tags)

    return {
        "fragments": fragment_count,
        "logical_placements": len(placements),
        "split_placements": sum(
            len(placement.fragments) > 1
            for placement in placements
        ),
        "complete": sum(placement.complete for placement in placements),
        "source_complete": sum(
            placement.source_complete
            for placement in placements
        ),
        "dimensions_match": sum(
            placement.dimensions_match
            for placement in placements
        ),
        "fragment_count_histogram": dict(sorted(histogram.items())),
        "semantic_counts": dict(semantic_counts.most_common()),
        "explicit_passage_placements": semantic_counts.get("passage", 0),
        "failure_examples": [
            {
                "id": placement.placement_id,
                "name": placement.name,
                "rotation": placement.rotation,
                "fragments": len(placement.fragments),
                "source_complete": placement.source_complete,
                "source_overlap_chunks": placement.source_overlap_chunks,
                "dimensions_match": placement.dimensions_match,
                "origin_chunks": {
                    "x": placement.origin_chunk_x,
                    "y": placement.origin_chunk_y,
                },
            }
            for placement in placements
            if not placement.complete
        ][:20],
    }
