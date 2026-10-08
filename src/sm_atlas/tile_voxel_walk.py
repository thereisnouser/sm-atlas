"""Experimental floor/clearance candidate routing on Scrap Mechanic tile voxels.

This does not account for asset collisions, ladders, ramps, or game physics.
Density threshold and one-metre steps are hypotheses, not verified walkability.
"""
from __future__ import annotations

from array import array
from collections import deque
import heapq
from math import ceil, floor, hypot, sqrt
from pathlib import Path

from .tile_voxel_space import _dimensions, _load_density_bytes
from .tile_file import probe_tile_nodes


def _candidate_foot_positions(
    volume: bytearray,
    dims: tuple[int, int, int],
    *,
    threshold: int,
    headroom: int,
) -> bytearray:
    sx, sy, sz = dims
    footprint = bytearray(len(volume))
    for x in range(sx):
        for y in range(sy):
            offset = (x * sy + y) * sz
            for z in range(1, sz - headroom + 1):
                support = volume[offset + z - 1]
                if support == 255 or (support & 15) < threshold:
                    continue
                if all(
                    volume[offset + z + h] != 255
                    and (volume[offset + z + h] & 15) < threshold
                    for h in range(headroom)
                ):
                    footprint[offset + z] = 1
    return footprint


def _neighbours(
    index: int,
    dims: tuple[int, int, int],
    *,
    max_step: int,
    volume: bytearray | None = None,
    density_threshold: int = 8,
    headroom: int = 2,
):
    sx, sy, sz = dims
    stride = sy * sz
    x, rem = divmod(index, stride)
    y, z = divmod(rem, sz)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        xx, yy = x + dx, y + dy
        if not (0 <= xx < sx and 0 <= yy < sy):
            continue
        base = (xx * sy + yy) * sz
        for dz in range(-max_step, max_step + 1):
            zz = z + dz
            if not 0 <= zz < sz:
                continue
            if dz > 0 and volume is not None:
                # Moving to a higher foot cell also requires room for the
                # player's head on the lower side of the step. The old graph
                # tested standing clearance only at the two endpoints.
                extra_clear = all(
                    z + headroom + rise < sz
                    and volume[index + headroom + rise] != 255
                    and (
                        volume[index + headroom + rise] & 0x0F
                    ) < density_threshold
                    for rise in range(dz)
                )
                if not extra_clear:
                    continue
            yield base + zz, dz


def _label_walk_components(
    footprint: bytearray,
    dims: tuple[int, int, int],
    *,
    max_step: int,
    volume: bytearray | None = None,
    density_threshold: int = 8,
    headroom: int = 2,
) -> tuple[array, list[dict[str, int]]]:
    labels = array("I", [0]) * len(footprint)
    components = []
    for seed, valid in enumerate(footprint):
        if not valid or labels[seed]:
            continue
        cid = len(components) + 1
        queue = deque([seed])
        labels[seed] = cid
        size = 0
        while queue:
            node = queue.popleft()
            size += 1
            for neighbour, _ in _neighbours(
                node, dims, max_step=max_step, volume=volume,
                density_threshold=density_threshold, headroom=headroom,
            ):
                if footprint[neighbour] and not labels[neighbour]:
                    labels[neighbour] = cid
                    queue.append(neighbour)
        components.append({"id": cid, "voxels": size})
    return labels, components


def _nearest_foot(
    point: tuple[float, float, float],
    labels: array,
    sizes: dict[int, int],
    dims: tuple[int, int, int],
    *,
    radius: float,
    min_component_size: int,
) -> dict[str, object] | None:
    sx, sy, sz = dims
    best = None
    for x in range(max(0, floor(point[0] - radius)),
                   min(sx - 1, ceil(point[0] + radius)) + 1):
        for y in range(max(0, floor(point[1] - radius)),
                       min(sy - 1, ceil(point[1] + radius)) + 1):
            for z in range(max(0, floor(point[2] - radius)),
                           min(sz - 1, ceil(point[2] + radius)) + 1):
                cid = labels[(x * sy + y) * sz + z]
                if not cid or sizes[cid] < min_component_size:
                    continue
                dist2 = sum(
                    (coordinate + 0.5 - target) ** 2
                    for coordinate, target in zip((x, y, z), point)
                )
                if dist2 > radius * radius:
                    continue
                candidate = (dist2, x, y, z, cid)
                if best is None or candidate < best:
                    best = candidate
    if best is None:
        return None
    dist2, x, y, z, cid = best
    return {
        "component": int(cid),
        "distance_m": round(sqrt(dist2), 3),
        "foot_voxel": (x, y, z),
    }


def _shortest_walk(
    start: tuple[int, int, int],
    end: tuple[int, int, int],
    footprint: bytearray,
    dims: tuple[int, int, int],
    *,
    max_step: int,
    volume: bytearray | None = None,
    density_threshold: int = 8,
    headroom: int = 2,
) -> dict[str, object] | None:
    _, sy, sz = dims

    def idx(point: tuple[int, int, int]) -> int:
        return (point[0] * sy + point[1]) * sz + point[2]

    def xyz(n: int) -> tuple[int, int, int]:
        x, rem = divmod(n, sy * sz)
        y, z = divmod(rem, sz)
        return x, y, z

    a, b = idx(start), idx(end)
    if not footprint[a] or not footprint[b]:
        return None
    best = {a: 0.0}
    previous: dict[int, int] = {}
    heap = [(0.0, a)]

    while heap:
        cost, node = heapq.heappop(heap)
        if cost > best.get(node, float("inf")) + 1e-9:
            continue
        if node == b:
            break
        for neighbour, dz in _neighbours(
            node, dims, max_step=max_step, volume=volume,
            density_threshold=density_threshold, headroom=headroom,
        ):
            if not footprint[neighbour]:
                continue
            alt = cost + hypot(1.0, dz)
            if alt + 1e-9 < best.get(neighbour, float("inf")):
                best[neighbour] = alt
                previous[neighbour] = node
                heapq.heappush(heap, (alt, neighbour))

    if b not in best:
        return None

    path = [b]
    while path[-1] != a:
        path.append(previous[path[-1]])
    path.reverse()
    points = [xyz(node) for node in path]
    climb = sum(max(0, q[2] - p[2]) for p, q in zip(points, points[1:]))
    descent = sum(max(0, p[2] - q[2]) for p, q in zip(points, points[1:]))
    rises = sum(q[2] > p[2] for p, q in zip(points, points[1:]))
    drops = sum(q[2] < p[2] for p, q in zip(points, points[1:]))
    return {
        "grid_steps": len(points) - 1,
        "level_steps": len(points) - 1 - rises - drops,
        "rise_steps": rises,
        "drop_steps": drops,
        "unverified_elevation_edges": rises + drops,
        "rise_clearance_checked": volume is not None,
        "length_m": round(best[b], 3),
        "climb_m": climb,
        "descent_m": descent,
        "min_z": min(point[2] for point in points),
        "max_z": max(point[2] for point in points),
        "foot_voxels": points,
    }


def probe_tile_voxel_walk(
    tile: str | Path,
    *,
    density_threshold: int = 8,
    headroom: int = 2,
    max_step: int = 1,
    min_component_size: int = 50,
    socket_radius: float = 5.0,
    from_socket: str | None = None,
    to_socket: str | None = None,
    max_grid_voxels: int = 4_000_000,
) -> dict[str, object]:
    if not 1 <= density_threshold <= 15:
        raise ValueError("density_threshold must be 1..15")
    if not 1 <= headroom <= 8:
        raise ValueError("headroom must be 1..8")
    if not 0 <= max_step <= 2:
        raise ValueError("max_step must be 0..2")
    if min_component_size < 1:
        raise ValueError("min_component_size must be >= 1")
    if not 0 < socket_radius <= 32:
        raise ValueError("socket_radius must be > 0 and <= 32")
    if (from_socket is None) != (to_socket is None):
        raise ValueError("both from_socket and to_socket are required")

    path = Path(tile).expanduser().resolve()
    dims = _dimensions(path)
    n = dims[0] * dims[1] * dims[2]
    if n > max_grid_voxels:
        raise ValueError(f"voxel grid too large ({n} > {max_grid_voxels})")

    volume, missing = _load_density_bytes(path, dims)
    footprint = _candidate_foot_positions(
        volume, dims, threshold=density_threshold, headroom=headroom,
    )
    labels, components = _label_walk_components(
        footprint, dims, max_step=max_step, volume=volume,
        density_threshold=density_threshold, headroom=headroom,
    )
    sizes = {int(c["id"]): c["voxels"] for c in components}
    sockets = []

    for chunk in probe_tile_nodes(path)["node_chunks"]:
        for node in chunk["nodes"]:
            pos = tuple(float(v) for v in node["tile_position"])
            nearest = _nearest_foot(
                pos, labels, sizes, dims, radius=socket_radius,
                min_component_size=min_component_size,
            )
            name = f"cell{chunk['cell']}:node{node['index']}"
            sockets.append({
                "socket": name,
                "tile_position": tuple(round(v, 3) for v in pos),
                "nearest_foot": nearest,
            })

    major = [c for c in components if c["voxels"] >= min_component_size]
    major.sort(key=lambda c: -c["voxels"])
    output: dict[str, object] = {
        "tile": str(path),
        "dimensions_m": dims,
        "density_threshold": density_threshold,
        "headroom_m": headroom,
        "max_step_m": max_step,
        "rise_clearance_checked": True,
        "socket_radius_m": socket_radius,
        "min_component_size": min_component_size,
        "unknown_voxels": missing,
        "candidate_foot_positions": footprint.count(1),
        "components": len(components),
        "major_components": major[:20],
        "sockets": sockets,
        "interpretation": "experimental_candidate_walking; not verified game navigation",
    }

    if from_socket is not None:
        lookup = {item["socket"]: item for item in sockets}
        if from_socket not in lookup or to_socket not in lookup:
            raise ValueError(
                "unknown socket; available: " + ", ".join(sorted(lookup))
            )
        source = lookup[from_socket]["nearest_foot"]
        target = lookup[to_socket]["nearest_foot"]
        path_result: dict[str, object] = {
            "from_socket": from_socket,
            "to_socket": to_socket,
            "status": "not_connected",
            "path": None,
        }
        if source is None or target is None:
            path_result["status"] = "socket_not_attached_to_major_floor"
        elif source["component"] != target["component"]:
            path_result["status"] = "different_candidate_floor_components"
        else:
            walk = _shortest_walk(
                source["foot_voxel"], target["foot_voxel"],
                footprint, dims, max_step=max_step, volume=volume,
                density_threshold=density_threshold, headroom=headroom,
            )
            if walk is not None:
                path_result["status"] = "candidate_path_found"
                path_result["path"] = walk
                path_result["socket_attachment"] = {
                    "source_offset_m": source["distance_m"],
                    "target_offset_m": target["distance_m"],
                    "validated_connection": False,
                }
        output["route"] = path_result
    return output
