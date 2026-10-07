from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


TILE_MAGIC = 0x454C4954
TILE_FILE_HEADER_FORMAT = "<II16sQIIIIIII"
TILE_FILE_HEADER_SIZE = struct.calcsize(TILE_FILE_HEADER_FORMAT)
TILE_CELL_HEADER_INTS = 97
TILE_CELL_HEADER_SIZE = TILE_CELL_HEADER_INTS * 4


class InvalidTileFile(ValueError):
    """Raised when a file does not look like a Scrap Mechanic .tile file."""


@dataclass(frozen=True)
class TileChunk:
    cell: int
    kind: str
    level: int | None
    count: int | None
    index: int
    compressed_size: int
    uncompressed_size: int

    def to_dict(self) -> dict[str, object]:
        return {
            "cell": self.cell,
            "kind": self.kind,
            "level": self.level,
            "count": self.count,
            "index": self.index,
            "compressed_size": self.compressed_size,
            "uncompressed_size": self.uncompressed_size,
        }


def _single_chunk(
    values: tuple[int, ...],
    *,
    cell: int,
    kind: str,
    base: int,
) -> TileChunk:
    count = values[base]
    index = values[base + 1]
    compressed = values[base + 2]
    size = values[base + 3]
    return TileChunk(
        cell=cell,
        kind=kind,
        level=None,
        count=count,
        index=index,
        compressed_size=compressed,
        uncompressed_size=size,
    )


def _level_chunks(
    values: tuple[int, ...],
    *,
    cell: int,
    kind: str,
    count_slice: slice | None,
    index_slice: slice,
    compressed_slice: slice,
    size_slice: slice,
) -> list[TileChunk]:
    indexes = values[index_slice]
    compressed = values[compressed_slice]
    sizes = values[size_slice]
    counts = (
        (None,) * len(indexes)
        if count_slice is None
        else values[count_slice]
    )
    return [
        TileChunk(
            cell=cell,
            kind=kind,
            level=level,
            count=counts[level],
            index=indexes[level],
            compressed_size=compressed[level],
            uncompressed_size=sizes[level],
        )
        for level in range(len(indexes))
    ]


def _parse_cell_chunks(
    data: bytes,
    *,
    offset: int,
    size: int,
    cell: int,
) -> list[TileChunk]:
    if size < TILE_CELL_HEADER_SIZE:
        raise InvalidTileFile(
            f"cell header size {size} is smaller than "
            f"{TILE_CELL_HEADER_SIZE}"
        )
    if offset < 0 or offset + TILE_CELL_HEADER_SIZE > len(data):
        raise InvalidTileFile("cell header extends beyond file")

    values = struct.unpack_from(
        f"<{TILE_CELL_HEADER_INTS}i",
        data,
        offset,
    )

    chunks: list[TileChunk] = []
    chunks.extend(
        _level_chunks(
            values,
            cell=cell,
            kind="mip",
            count_slice=None,
            index_slice=slice(0, 6),
            compressed_slice=slice(6, 12),
            size_slice=slice(12, 18),
        )
    )
    chunks.append(
        TileChunk(
            cell=cell,
            kind="clutter",
            level=None,
            count=None,
            index=values[18],
            compressed_size=values[19],
            uncompressed_size=values[20],
        )
    )
    chunks.extend(
        _level_chunks(
            values,
            cell=cell,
            kind="assets",
            count_slice=slice(21, 25),
            index_slice=slice(25, 29),
            compressed_slice=slice(29, 33),
            size_slice=slice(33, 37),
        )
    )

    for kind, base in (
        ("blueprint", 37),
        ("node", 41),
        ("script", 45),
        ("prefab", 49),
        ("decal", 53),
    ):
        chunks.append(
            _single_chunk(
                values,
                cell=cell,
                kind=kind,
                base=base,
            )
        )

    chunks.extend(
        _level_chunks(
            values,
            cell=cell,
            kind="harvestable",
            count_slice=slice(57, 61),
            index_slice=slice(61, 65),
            compressed_slice=slice(65, 69),
            size_slice=slice(69, 73),
        )
    )
    chunks.extend(
        _level_chunks(
            values,
            cell=cell,
            kind="kinematics",
            count_slice=slice(73, 77),
            index_slice=slice(77, 81),
            compressed_slice=slice(81, 85),
            size_slice=slice(85, 89),
        )
    )
    chunks.append(
        _single_chunk(
            values,
            cell=cell,
            kind="unknown",
            base=89,
        )
    )
    chunks.append(
        _single_chunk(
            values,
            cell=cell,
            kind="voxel_terrain",
            base=93,
        )
    )

    return chunks


def _chunk_present(chunk: TileChunk) -> bool:
    return (
        chunk.index > 0
        and chunk.compressed_size > 0
        and chunk.uncompressed_size > 0
    )


def probe_tile(path: str | Path) -> dict[str, object]:
    tile_path = Path(path).expanduser().resolve()
    if not tile_path.is_file():
        raise FileNotFoundError(tile_path)

    data = tile_path.read_bytes()
    if len(data) < TILE_FILE_HEADER_SIZE:
        raise InvalidTileFile("file is smaller than the .tile header")

    (
        magic,
        version,
        uuid_bytes,
        creator_id,
        width,
        height,
        cell_header_offset,
        cell_header_size,
        unknown_1,
        unknown_2,
        tile_type,
    ) = struct.unpack_from(
        TILE_FILE_HEADER_FORMAT,
        data,
        0,
    )

    if magic != TILE_MAGIC:
        raise InvalidTileFile("missing TILE magic")
    if width <= 0 or height <= 0:
        raise InvalidTileFile(
            f"invalid tile dimensions: {width}x{height}"
        )

    cell_count = width * height
    header_end = (
        cell_header_offset
        + cell_header_size * cell_count
    )
    if cell_header_offset < TILE_FILE_HEADER_SIZE:
        raise InvalidTileFile("cell header offset overlaps file header")
    if header_end > len(data):
        raise InvalidTileFile("cell header table extends beyond file")

    chunks: list[TileChunk] = []
    for cell in range(cell_count):
        chunks.extend(
            _parse_cell_chunks(
                data,
                offset=cell_header_offset + cell * cell_header_size,
                size=cell_header_size,
                cell=cell,
            )
        )

    present = [
        chunk
        for chunk in chunks
        if _chunk_present(chunk)
    ]

    invalid_ranges = []
    for chunk in present:
        end = chunk.index + chunk.compressed_size
        if chunk.index < 0 or end > len(data):
            invalid_ranges.append(chunk.to_dict())

    kinds: dict[str, dict[str, int]] = {}
    for chunk in present:
        summary = kinds.setdefault(
            chunk.kind,
            {
                "chunks": 0,
                "items": 0,
                "compressed_bytes": 0,
                "uncompressed_bytes": 0,
            },
        )
        summary["chunks"] += 1
        summary["items"] += max(chunk.count or 0, 0)
        summary["compressed_bytes"] += chunk.compressed_size
        summary["uncompressed_bytes"] += chunk.uncompressed_size

    return {
        "path": str(tile_path),
        "file_size": len(data),
        "version": version,
        "uuid_hex": uuid_bytes.hex(),
        "creator_id": creator_id,
        "width": width,
        "height": height,
        "cells": cell_count,
        "cell_header_offset": cell_header_offset,
        "cell_header_size": cell_header_size,
        "unknown_1": unknown_1,
        "unknown_2": unknown_2,
        "type": tile_type,
        "content": kinds,
        "invalid_chunk_ranges": invalid_ranges,
        "chunks": [
            chunk.to_dict()
            for chunk in present
        ],
    }
