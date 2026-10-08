"""Experimental .tile placement inventory.

The game's chunk name "unknown" is deliberately preserved: a transform
and UUID alone do not identify an object's mesh, collision, or purpose.
"""
from __future__ import annotations

from collections import Counter
from math import isfinite
from pathlib import Path
import struct

from .tile_file import InvalidTileFile, decompress_lz4_block, probe_tile


# Sizes observed in the Drill2 passage tile (version 15). Strict validation
# prevents silently mis-decoding different tile versions or object formats.
_RECORD_SIZES = {"unknown": 69, "harvestable": 65}


def placements_near_candidate_route(
    placements: list[dict[str, object]],
    foot_voxels: list[tuple[int, int, int]],
    *,
    radius_m: float = 5.0,
) -> list[dict[str, object]]:
    """Return nearby placement *origins*, not asset collision overlaps."""
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")
    if not foot_voxels:
        return []
    results = []
    for placement in placements:
        pos = placement["tile_position"]
        nearest = min(
            (
                sum((p + 0.5 - v) ** 2 for p, v in zip(foot, pos)),
                foot,
            )
            for foot in foot_voxels
        )
        if nearest[0] <= radius_m ** 2:
            results.append({
                "kind": placement["kind"],
                "index": placement["index"],
                "cell": placement["cell"],
                "uuid_hex": placement["uuid_hex"],
                "tile_position": placement["tile_position"],
                "distance_to_footpath_m": round(nearest[0] ** 0.5, 3),
                "nearest_foot": nearest[1],
            })
    results.sort(key=lambda entry: entry["distance_to_footpath_m"])
    return results


def probe_tile_objects(
    path: str | Path,
    *,
    examples: int = 12,
) -> dict[str, object]:
    if examples < 0:
        raise ValueError("examples must be >= 0")
    tile_path = Path(path).expanduser().resolve()
    tile = probe_tile(tile_path)
    raw = tile_path.read_bytes()
    placements: list[dict[str, object]] = []
    chunk_summaries = []
    for chunk in tile["chunks"]:
        kind = chunk["kind"]
        if kind not in _RECORD_SIZES:
            continue
        count = int(chunk["count"] or 0)
        if count < 1:
            continue
        offset = int(chunk["index"])
        length = int(chunk["compressed_size"])
        data = decompress_lz4_block(
            raw[offset:offset + length],
            expected_size=chunk["uncompressed_size"],
        )
        record_size = _RECORD_SIZES[kind]
        if len(data) != count * record_size:
            raise InvalidTileFile(
                f"unsupported {kind} placement layout in cell {chunk['cell']}: "
                f"count={count}, decoded_bytes={len(data)}, "
                f"expected_stride={record_size}"
            )

        cell = int(chunk["cell"])
        cell_x = cell % int(tile["width"])
        cell_y = cell // int(tile["width"])
        for i in range(count):
            record = data[i * record_size:(i + 1) * record_size]
            position = struct.unpack_from("<3f", record)
            rotation = struct.unpack_from("<4f", record, 12)
            scale = struct.unpack_from("<3f", record, 28)
            if not all(isfinite(v) for v in (*position, *rotation, *scale)):
                raise InvalidTileFile(f"{kind} contains nonfinite transform")
            # Positions are local to the chunk cell; scale/rotation/UUID alone
            # cannot supply collision bounds.
            tile_position = (
                position[0] + 64.0 * cell_x,
                position[1] + 64.0 * cell_y,
                position[2],
            )
            placements.append({
                "kind": kind,
                "cell": cell,
                "index": i,
                "tile_position": tuple(round(v, 6) for v in tile_position),
                "rotation": tuple(round(v, 6) for v in rotation),
                "scale": tuple(round(v, 6) for v in scale),
                "uuid_hex": record[40:56].hex(),
                "trailing_bytes_hex": record[56:].hex(),
            })
        chunk_summaries.append({
            "kind": kind,
            "cell": cell,
            "count": count,
            "record_size": record_size,
        })

    counts = Counter(p["kind"] for p in placements)
    groups = Counter((p["kind"], p["uuid_hex"]) for p in placements)
    return {
        "path": str(tile_path),
        "version": tile["version"],
        "total_placements": len(placements),
        "by_kind": dict(sorted(counts.items())),
        "groups": [
            {"kind": kind, "uuid_hex": uuid, "count": count}
            for (kind, uuid), count in sorted(groups.items())
        ],
        "chunk_summaries": chunk_summaries,
        "examples": placements[:examples],
        "placements": placements,
        "interpretation": (
            "transform_and_uuid_only; object mesh, type, and collision "
            "are not decoded"
        ),
    }
