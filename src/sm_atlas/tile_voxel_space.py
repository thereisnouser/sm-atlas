"""Experimental 3D candidate-void connectivity for Scrap Mechanic .tile voxels.

Low packed-density values (4/5-bit hypotheses) are candidate empty space,
NOT validated walkability. The tile byte packing is not yet confirmed.
Collision from placed assets, prefabs, and blueprints is not incorporated.
"""
from __future__ import annotations

from array import array
from collections import deque
from math import ceil, floor, sqrt
from pathlib import Path
import re
import struct

from .tile_file import (
    InvalidTileFile,
    VOXEL_RECORD_SIZE,
    decompress_lz4_block,
    probe_tile,
    probe_tile_nodes,
)


def _dimensions(path: Path) -> tuple[int, int, int]:
    match = re.search(r"_(\d+)x(\d+)x(\d+)\.tile$", path.name, flags=re.I)
    if match is None:
        raise ValueError("tile filename must end with _WxDxH.tile")
    return tuple(16 * int(value) for value in match.groups())


def _load_density_bytes(
    path: Path,
    dims: tuple[int, int, int],
    *,
    return_written: bool = False,
) -> tuple[bytearray, int] | tuple[bytearray, int, bytearray]:
    """Read byte volume, optionally returning *record occupancy* per voxel.

    A literal 0xFF in a written record is different from an absent record.
    Keep the two-result legacy contract for existing candidate navigation;
    research callers can request the actual occupancy mask.
    """
    sx, sy, sz = dims
    data = path.read_bytes()
    meta = probe_tile(path)
    volume = bytearray(b"\xff") * (sx * sy * sz)
    written = bytearray(sx * sy * sz)
    width_cells = int(meta["width"])

    for chunk in meta["chunks"]:
        if chunk["kind"] != "voxel_terrain":
            continue
        compressed = data[
            chunk["index"]:chunk["index"] + chunk["compressed_size"]
        ]
        decoded = decompress_lz4_block(
            compressed,
            expected_size=chunk["uncompressed_size"],
        )
        if len(decoded) % VOXEL_RECORD_SIZE:
            raise InvalidTileFile("unaligned voxel terrain records")
        if (
            chunk["count"] is not None
            and len(decoded) // VOXEL_RECORD_SIZE != chunk["count"]
        ):
            raise InvalidTileFile("voxel terrain record count mismatch")

        cell_x = int(chunk["cell"]) % width_cells
        cell_y = int(chunk["cell"]) // width_cells

        for off in range(0, len(decoded), VOXEL_RECORD_SIZE):
            bx, by, bz = struct.unpack_from("<3i", decoded, off)
            payload = decoded[off + 12:off + VOXEL_RECORD_SIZE]
            gx0 = cell_x * 64 + bx * 16
            gy0 = cell_y * 64 + by * 16
            gz0 = bz * 16
            zlo = max(0, -gz0)
            zhi = min(16, sz - gz0)
            if zhi <= zlo:
                continue

            # Local byte order established by block-boundary continuity:
            # Z changes fastest, then Y, then X.
            for x in range(16):
                gx = gx0 + x
                if not 0 <= gx < sx:
                    continue
                for y in range(16):
                    gy = gy0 + y
                    if not 0 <= gy < sy:
                        continue
                    start = (gx * sy + gy) * sz + gz0 + zlo
                    source = (x * 16 + y) * 16 + zlo
                    end = start + (zhi - zlo)
                    if any(written[start:end]):
                        raise InvalidTileFile("overlapping voxel terrain records")
                    volume[start:end] = payload[source:source + zhi - zlo]
                    written[start:end] = b"\x01" * (zhi - zlo)

    missing_count = written.count(0)
    if return_written:
        return volume, missing_count, written
    return volume, missing_count


def _components(
    volume: bytearray,
    dims: tuple[int, int, int],
    threshold: int,
    density_bits: int = 4,
) -> tuple[array, list[dict[str, object]]]:
    sx, sy, sz = dims
    stride = sy * sz
    mask = (1 << density_bits) - 1
    labels = array("I", [0]) * len(volume)
    components: list[dict[str, object]] = []

    for seed, value in enumerate(volume):
        if labels[seed] or value == 255 or (value & mask) >= threshold:
            continue
        cid = len(components) + 1
        labels[seed] = cid
        queue = deque((seed,))
        size = 0
        lower = [sx, sy, sz]
        upper = [-1, -1, -1]

        while queue:
            p = queue.popleft()
            x = p // stride
            y = (p // sz) % sy
            z = p % sz
            size += 1
            for axis, coordinate in enumerate((x, y, z)):
                lower[axis] = min(lower[axis], coordinate)
                upper[axis] = max(upper[axis], coordinate)

            neighbours = []
            if x:
                neighbours.append(p - stride)
            if x + 1 < sx:
                neighbours.append(p + stride)
            if y:
                neighbours.append(p - sz)
            if y + 1 < sy:
                neighbours.append(p + sz)
            if z:
                neighbours.append(p - 1)
            if z + 1 < sz:
                neighbours.append(p + 1)

            for q in neighbours:
                raw = volume[q]
                if not labels[q] and raw != 255 and (raw & mask) < threshold:
                    labels[q] = cid
                    queue.append(q)

        components.append(
            {
                "id": cid,
                "voxels": size,
                "min": tuple(lower),
                "max": tuple(upper),
            }
        )

    return labels, components


def _nearest_component(
    point: tuple[float, float, float],
    labels: array,
    dims: tuple[int, int, int],
    sizes: dict[int, int],
    radius: float,
    min_size: int,
) -> dict[str, object] | None:
    sx, sy, sz = dims
    best: tuple[float, int, tuple[int, int, int]] | None = None

    for x in range(
        max(0, floor(point[0] - radius)),
        min(sx - 1, ceil(point[0] + radius)) + 1,
    ):
        for y in range(
            max(0, floor(point[1] - radius)),
            min(sy - 1, ceil(point[1] + radius)) + 1,
        ):
            for z in range(
                max(0, floor(point[2] - radius)),
                min(sz - 1, ceil(point[2] + radius)) + 1,
            ):
                dist2 = sum(
                    (coordinate + 0.5 - target) ** 2
                    for coordinate, target in zip((x, y, z), point)
                )
                if dist2 > radius * radius:
                    continue
                cid = labels[(x * sy + y) * sz + z]
                if cid == 0 or sizes[cid] < min_size:
                    continue
                candidate = (dist2, cid, (x, y, z))
                if best is None or candidate < best:
                    best = candidate

    if best is None:
        return None

    return {
        "component": best[1],
        "distance_m": round(sqrt(best[0]), 3),
        "nearest_voxel": best[2],
    }


def probe_tile_voxel_space(
    tile: str | Path,
    *,
    density_threshold: int | None = None,
    density_bits: int = 4,
    min_component_size: int = 100,
    socket_radius: float = 5.0,
    max_grid_voxels: int = 4_000_000,
) -> dict[str, object]:
    """Match tunnel sockets to candidate connected voids without routing."""
    if density_bits not in (4, 5):
        raise ValueError("density_bits must be 4 or 5")
    if density_threshold is None:
        density_threshold = 1 << (density_bits - 1)
    if not 1 <= density_threshold <= (1 << density_bits) - 1:
        raise ValueError("density_threshold outside packing density range")
    if min_component_size < 1:
        raise ValueError("min_component_size must be >= 1")
    if not 0 < socket_radius <= 32:
        raise ValueError("socket_radius must be > 0 and <= 32")

    path = Path(tile).expanduser().resolve()
    dims = _dimensions(path)
    count = dims[0] * dims[1] * dims[2]
    if count > max_grid_voxels:
        raise ValueError(f"voxel grid too large ({count} > {max_grid_voxels})")

    volume, missing = _load_density_bytes(path, dims)
    labels, components = _components(
        volume, dims, density_threshold, density_bits=density_bits,
    )
    sizes = {
        int(component["id"]): int(component["voxels"])
        for component in components
    }
    sockets = []
    groups: dict[int, list[str]] = {}

    for chunk in probe_tile_nodes(path)["node_chunks"]:
        for node in chunk["nodes"]:
            point = tuple(float(p) for p in node["tile_position"])
            nearest = _nearest_component(
                point, labels, dims, sizes, socket_radius, min_component_size,
            )
            params = node["params"]
            tunnel = params.get("tunnel") if isinstance(params, dict) else None
            tunnel_type = tunnel.get("type") if isinstance(tunnel, dict) else None
            socket_id = f"cell{chunk['cell']}:node{node['index']}"
            sockets.append(
                {
                    "socket": socket_id,
                    "type": tunnel_type,
                    "tile_position": tuple(round(v, 3) for v in point),
                    "nearest": nearest,
                }
            )
            if nearest is not None:
                groups.setdefault(int(nearest["component"]), []).append(socket_id)

    major = [
        component for component in components
        if component["voxels"] >= min_component_size
    ]
    major.sort(key=lambda component: -component["voxels"])

    return {
        "tile": str(path),
        "dimensions_m": dims,
        "density_threshold": density_threshold,
        "density_bits": density_bits,
        "unknown_voxels": missing,
        "component_count": len(components),
        "major_components": major,
        "sockets": sockets,
        "socket_groups": [
            {"component": cid, "sockets": group}
            for cid, group in sorted(groups.items())
        ],
        "interpretation": "candidate_voids_only; does not establish walkable paths",
    }
