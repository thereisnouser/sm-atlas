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
    density_bits: int = 4,
) -> bytearray:
    sx, sy, sz = dims
    density_mask = (1 << density_bits) - 1
    footprint = bytearray(len(volume))
    for x in range(sx):
        for y in range(sy):
            offset = (x * sy + y) * sz
            for z in range(1, sz - headroom + 1):
                support = volume[offset + z - 1]
                if support == 255 or (support & density_mask) < threshold:
                    continue
                if all(
                    volume[offset + z + h] != 255
                    and (volume[offset + z + h] & density_mask) < threshold
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
    density_bits: int = 4,
):
    sx, sy, sz = dims
    stride = sy * sz
    density_mask = (1 << density_bits) - 1
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
            if dz != 0 and volume is not None:
                # Check extra head clearance over the lower foot position,
                # independent of travel direction. This keeps floor edges
                # symmetric so connected-component labels stay meaningful.
                lower_index, lower_z = (
                    (index, z) if dz > 0 else (base + zz, zz)
                )
                extra_clear = all(
                    lower_z + headroom + rise < sz
                    and volume[lower_index + headroom + rise] != 255
                    and (
                        volume[lower_index + headroom + rise] & density_mask
                    ) < density_threshold
                    for rise in range(abs(dz))
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
    density_bits: int = 4,
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
                density_bits=density_bits,
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
    density_bits: int = 4,
) -> dict[str, object] | None:
    _, sy, sz = dims
    density_mask = (1 << density_bits) - 1

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
            density_bits=density_bits,
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
    elevation_edges = []
    if volume is not None:
        for edge_index, (p, q) in enumerate(zip(points, points[1:])):
            dz = q[2] - p[2]
            if not dz:
                continue
            source_index = (p[0] * sy + p[1]) * sz + p[2] - 1
            target_index = (q[0] * sy + q[1]) * sz + q[2] - 1
            a_raw = int(volume[source_index])
            b_raw = int(volume[target_index])
            elevation_edges.append({
                "step_index": edge_index,
                "from_foot": p,
                "to_foot": q,
                "delta_z_m": dz,
                "from_support_raw": a_raw,
                "to_support_raw": b_raw,
                "from_support_density": a_raw & density_mask,
                "to_support_density": b_raw & density_mask,
                "has_partial_support_density": (
                    (a_raw & density_mask) < density_mask
                    or (b_raw & density_mask) < density_mask
                ),
            })
    return {
        "elevation_support_summary": {
            "density_bits": density_bits,
            "max_density": density_mask,
            "edges_sampled": len(elevation_edges),
            "partial_density_edges": sum(
                edge["has_partial_support_density"] for edge in elevation_edges
            ),
            "both_full_density_edges": sum(
                not edge["has_partial_support_density"] for edge in elevation_edges
            ),
            "interpretation": (
                "intermediate density suggests a surface boundary; "
                "does not prove a traversable slope"
            ),
        },
        "elevation_edge_samples": elevation_edges,
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


def _explain_component_gap(
    labels: array,
    dims: tuple[int, int, int],
    component_a: int,
    component_b: int,
    *,
    max_step: int,
    volume: bytearray,
    density_threshold: int,
    headroom: int,
    density_bits: int = 4,
    examples_per_reason: int = 3,
) -> dict[str, object]:
    """Find adjacent candidate floors blocked by slope or headroom rules.

    Explains rejected voxel-graph edges only. It does not prove actual
    collision or find bridges represented by separate game assets.
    """
    sx, sy, sz = dims
    stride = sy * sz
    density_mask = (1 << density_bits) - 1
    causes: dict[str, int] = {}
    examples: dict[str, list[dict[str, object]]] = {}
    nearest: dict[str, object] | None = None
    search_z = max(2, max_step)

    for p, cid in enumerate(labels):
        if cid != component_a:
            continue
        x, rem = divmod(p, stride)
        y, z = divmod(rem, sz)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            xx, yy = x + dx, y + dy
            if not (0 <= xx < sx and 0 <= yy < sy):
                continue
            base = (xx * sy + yy) * sz
            for dz in range(-search_z, search_z + 1):
                zz = z + dz
                if not 0 <= zz < sz or labels[base + zz] != component_b:
                    continue
                if abs(dz) > max_step:
                    reason = "step_exceeds_limit"
                    blocker = None
                else:
                    low_index, low_z = (
                        (p, z) if dz > 0 else (base + zz, zz)
                    )
                    blocker = None
                    for rise in range(abs(dz)):
                        sample_z = low_z + headroom + rise
                        if sample_z >= sz:
                            blocker = {
                                "position": (
                                    (x, y, sample_z)
                                    if dz > 0 else (xx, yy, sample_z)
                                ),
                                "reason": "outside_tile",
                            }
                            break
                        raw = volume[low_index + headroom + rise]
                        if raw == 255 or (raw & density_mask) >= density_threshold:
                            blocker = {
                                "position": (
                                    (x, y, sample_z)
                                    if dz > 0 else (xx, yy, sample_z)
                                ),
                                "raw": int(raw),
                                "density": int(raw & density_mask),
                            }
                            break
                    reason = (
                        "low_side_headroom_blocked"
                        if blocker is not None
                        else "unexplained_graph_disconnect"
                    )

                from_point = (x, y, z)
                to_point = (xx, yy, zz)
                entry: dict[str, object] = {
                    "from_foot": from_point,
                    "to_foot": to_point,
                    "delta_z_m": dz,
                    "distance_m": round(hypot(1.0, dz), 3),
                }
                if blocker is not None:
                    entry["blocker"] = blocker
                causes[reason] = causes.get(reason, 0) + 1
                examples.setdefault(reason, [])
                if len(examples[reason]) < examples_per_reason:
                    examples[reason].append(entry)
                if nearest is None or entry["distance_m"] < nearest["distance_m"]:
                    nearest = entry

    return {
        "from_component": component_a,
        "to_component": component_b,
        "reason_counts": causes,
        "examples": examples,
        "closest_adjacent_candidate": nearest,
        "interpretation": "blocked_voxel_edges_only; not verified game collision",
    }


def _socket_inward_profile(
    point: tuple[float, float, float],
    volume: bytearray,
    dims: tuple[int, int, int],
    *,
    threshold: int,
    sample_cells: int = 9,
    density_bits: int = 4,
) -> dict[str, object]:
    """Inspect terrain voxels from the socket centre toward the tile inside.

    This is a 1D candidate-density survey, not an actual entrance collider
    test: saved socket positions can lie within the surface boundary band.
    """
    sx, sy, sz = dims
    density_mask = (1 << density_bits) - 1
    x, y, z = point
    boundaries = (
        (x, "x-", (1, 0)),
        (sx - x, "x+", (-1, 0)),
        (y, "y-", (0, 1)),
        (sy - y, "y+", (0, -1)),
    )
    _, face, direction = min(boundaries, key=lambda part: part[0])
    bx, by, bz = floor(x), floor(y), floor(z)
    samples: list[dict[str, object]] = []
    first_open = None
    reblocked = False

    for step in range(sample_cells):
        xx = bx + direction[0] * step
        yy = by + direction[1] * step
        if not (0 <= xx < sx and 0 <= yy < sy and 0 <= bz < sz):
            break
        value = int(volume[(xx * sy + yy) * sz + bz])
        candidate_open = value != 255 and (value & 0x0F) < threshold
        samples.append({
            "inward_cells": step,
            "voxel": (xx, yy, bz),
            "raw": value,
            "density": value & 0x0F if value != 255 else None,
            "candidate_open": candidate_open,
        })
        if candidate_open and first_open is None:
            first_open = (xx, yy, bz)
        elif not candidate_open and first_open is not None:
            reblocked = True

    return {
        "face": face,
        "first_open_voxel": first_open,
        "first_open_offset_cells": next(
            (
                sample["inward_cells"] for sample in samples
                if sample["candidate_open"]
            ),
            None,
        ),
        "reblocked_after_first_open": reblocked,
        "samples": samples,
    }


def _straight_candidate_space(
    start: tuple[int, int, int],
    end: tuple[int, int, int],
    volume: bytearray,
    dims: tuple[int, int, int],
    *,
    threshold: int,
    substep_m: float = 0.25,
    density_bits: int = 4,
) -> dict[str, object]:
    """Check only the centreline between candidate-open voxels.

    Clear centreline does NOT mean a human-sized actor can move there.
    """
    sx, sy, sz = dims
    density_mask = (1 << density_bits) - 1
    start_center = tuple(coord + 0.5 for coord in start)
    end_center = tuple(coord + 0.5 for coord in end)
    length = sqrt(sum(
        (b - a) ** 2 for a, b in zip(start_center, end_center)
    ))
    steps = max(1, ceil(length / substep_m))
    for step in range(steps + 1):
        t = step / steps
        xyz = tuple(
            floor(a + (b - a) * t)
            for a, b in zip(start_center, end_center)
        )
        x, y, z = xyz
        if not (0 <= x < sx and 0 <= y < sy and 0 <= z < sz):
            return {
                "status": "outside_tile",
                "first_blocker": {"voxel": xyz},
            }
        raw = int(volume[(x * sy + y) * sz + z])
        if raw == 255 or (raw & density_mask) >= threshold:
            return {
                "status": "candidate_solid_intersection",
                "first_blocker": {
                    "voxel": xyz,
                    "raw": raw,
                    "density": raw & density_mask if raw != 255 else None,
                },
            }
    return {"status": "clear_centreline", "first_blocker": None}


def probe_tile_voxel_walk(
    tile: str | Path,
    *,
    density_threshold: int | None = None,
    density_bits: int = 4,
    headroom: int = 2,
    max_step: int = 1,
    min_component_size: int = 50,
    socket_radius: float = 5.0,
    from_socket: str | None = None,
    to_socket: str | None = None,
    max_grid_voxels: int = 4_000_000,
) -> dict[str, object]:
    if density_bits not in (4, 5):
        raise ValueError("density_bits must be 4 or 5")
    if density_threshold is None:
        density_threshold = 1 << (density_bits - 1)
    if not 1 <= density_threshold <= (1 << density_bits) - 1:
        raise ValueError("density_threshold outside packing density range")
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
        density_bits=density_bits,
    )
    labels, components = _label_walk_components(
        footprint, dims, max_step=max_step, volume=volume,
        density_threshold=density_threshold, headroom=headroom,
        density_bits=density_bits,
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
            nearest_any = _nearest_foot(
                pos, labels, sizes, dims, radius=socket_radius,
                min_component_size=1,
            )
            name = f"cell{chunk['cell']}:node{node['index']}"
            entrance = _socket_inward_profile(
                pos, volume, dims, threshold=density_threshold,
                density_bits=density_bits,
            )
            to_major = None
            if (
                entrance["first_open_voxel"] is not None
                and nearest is not None
            ):
                to_major = _straight_candidate_space(
                    entrance["first_open_voxel"],
                    nearest["foot_voxel"],
                    volume, dims, threshold=density_threshold,
                    density_bits=density_bits,
                )
            entrance["straight_to_major_floor"] = to_major
            sockets.append({
                "socket": name,
                "tile_position": tuple(round(v, 3) for v in pos),
                "nearest_foot": nearest,
                "nearest_any_foot": nearest_any,
                "inward_terrain_probe": entrance,
            })

    major = [c for c in components if c["voxels"] >= min_component_size]
    major.sort(key=lambda c: -c["voxels"])
    output: dict[str, object] = {
        "tile": str(path),
        "dimensions_m": dims,
        "density_threshold": density_threshold,
        "density_bits": density_bits,
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
            path_result["gap_diagnostics"] = _explain_component_gap(
                labels, dims, source["component"], target["component"],
                max_step=max_step, volume=volume,
                density_threshold=density_threshold, headroom=headroom,
                density_bits=density_bits,
            )
        else:
            walk = _shortest_walk(
                source["foot_voxel"], target["foot_voxel"],
                footprint, dims, max_step=max_step, volume=volume,
                density_threshold=density_threshold, headroom=headroom,
                density_bits=density_bits,
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
