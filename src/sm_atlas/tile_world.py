"""Match a saved underground tile instance to its tile-local sockets.

This reports geometry hypotheses and alignment evidence; it neither loads
the game's physics mesh nor provides an in-game World userdata.
"""
from __future__ import annotations

from math import hypot, isfinite
from pathlib import Path
from uuid import UUID

from .database import SaveDatabase
from .tile_file import InvalidTileFile, probe_tile, probe_tile_nodes
from .tile_voxel_space import _dimensions
from .tile_voxel_walk import _load_density_bytes, _surface_sample_height
from .underground_topology import LayoutNode, build_layout_topology
from .underground_tunnels import _extract_tunnels, _load_terrain_table


def tile_to_world(
    node: LayoutNode,
    tile_dimensions: tuple[int, int, int],
    point: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Use the saved quarter-turn placement; local coordinates are metres."""
    width, depth, _ = tile_dimensions
    x, y, z = point
    rotation = node.rotation & 3
    if rotation == 1:
        dx, dy = depth - y, x
    elif rotation == 2:
        dx, dy = width - x, depth - y
    elif rotation == 3:
        dx, dy = y, width - x
    else:
        dx, dy = x, y
    return node.min_x + dx, node.min_y + dy, node.min_z + z


def world_to_tile(
    node: LayoutNode,
    tile_dimensions: tuple[int, int, int],
    point: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Inverse of tile_to_world for inspecting observed game measurements."""
    width, depth, _ = tile_dimensions
    x, y, z = (
        point[0] - node.min_x,
        point[1] - node.min_y,
        point[2] - node.min_z,
    )
    rotation = node.rotation & 3
    if rotation == 1:
        return y, depth - x, z
    if rotation == 2:
        return width - x, depth - y, z
    if rotation == 3:
        return width - y, x, z
    return x, y, z


def _verify_placement(
    node: LayoutNode,
    tile_dimensions: tuple[int, int, int],
    header_uuid: str,
) -> None:
    if node.tile_uuid is None or node.tile_uuid.lower() != header_uuid.lower():
        raise ValueError(
            "layout node tile UUID does not match the supplied .tile file"
        )
    x, y, z = tile_dimensions
    expected = (y, x, z) if node.rotation & 1 else (x, y, z)
    actual = (
        node.max_x - node.min_x,
        node.max_y - node.min_y,
        node.max_z - node.min_z,
    )
    if any(abs(a - b) > 1e-4 for a, b in zip(actual, expected)):
        raise ValueError(
            f"layout node bounds {actual} do not match rotated .tile "
            f"dimensions {expected}"
        )


def _match_saved_tunnels(
    sockets: list[dict[str, object]],
    tunnels: list[dict],
    *,
    tolerance_m: float,
) -> list[dict[str, object]]:
    """Match transformed sockets to independent saved tunnel endpoints."""
    matches: list[dict[str, object]] = []
    for tunnel in tunnels:
        points = tunnel["points"]
        for end_name, position in (("start", points[0]), ("end", points[-1])):
            distances = sorted(
                (
                    hypot(
                        hypot(
                            position[0] - socket["world_position"][0],
                            position[1] - socket["world_position"][1],
                        ),
                        position[2] - socket["world_position"][2],
                    ),
                    socket["socket"],
                )
                for socket in sockets
            )
            if not distances or distances[0][0] > tolerance_m:
                continue
            # Two sockets equally near the same endpoint are ambiguous:
            # do not use either as placement calibration evidence.
            if len(distances) > 1 and distances[1][0] <= tolerance_m:
                continue
            distance, socket_name = distances[0]
            matches.append({
                "tunnel_id": int(tunnel["id"]),
                "tunnel_type": str(tunnel["type"]),
                "end": end_name,
                "socket": socket_name,
                "saved_world_position": tuple(round(v, 6) for v in position),
                "residual_m": round(distance, 6),
            })
    return sorted(matches, key=lambda match: (
        match["socket"], match["tunnel_id"], match["end"],
    ))


def _parse_edge_coordinate(value: str) -> tuple[int, int, int]:
    parts = value.split(",")
    if len(parts) != 3:
        raise ValueError("edge points must be x,y,z voxel coordinates")
    try:
        return tuple(int(part.strip()) for part in parts)
    except ValueError as exc:
        raise ValueError("edge points must be integer x,y,z voxels") from exc


def _edge_measurement_samples(
    node: LayoutNode,
    dimensions: tuple[int, int, int],
    volume: bytearray,
    edge: tuple[tuple[int, int, int], tuple[int, int, int]],
    *,
    density_bits: int,
    density_threshold: int,
) -> dict[str, object]:
    a, b = edge
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx * dx + dy * dy != 1:
        raise ValueError("edge XY endpoints must be cardinal neighbours")
    za = _surface_sample_height(
        a, volume, dimensions,
        density_bits=density_bits, density_threshold=density_threshold,
    )
    zb = _surface_sample_height(
        b, volume, dimensions,
        density_bits=density_bits, density_threshold=density_threshold,
    )
    if za is None or zb is None:
        raise ValueError(
            "edge endpoints have no candidate vertical iso-crossing "
            "for the selected density model"
        )

    samples = []
    for lateral in (-0.5, 0.0, 0.5):
        for index in range(5):
            t = index / 4
            local = (
                a[0] + 0.5 + t * dx - lateral * dy,
                a[1] + 0.5 + t * dy + lateral * dx,
                za + t * (zb - za),
            )
            world = tile_to_world(node, dimensions, local)
            samples.append({
                "fraction": t,
                "lateral_offset_m": lateral,
                "tile_xy": tuple(round(x, 4) for x in local[:2]),
                "world_xy": tuple(round(x, 4) for x in world[:2]),
                "estimated_surface_world_z": round(world[2], 4),
                "note": "linear estimate; not engine collision height",
            })
    endpoints = [
        {
            "tile_foot_voxel": list(p),
            "world_foot_voxel_reference": [
                round(v, 6) for v in tile_to_world(
                    node, dimensions,
                    (p[0] + 0.5, p[1] + 0.5, p[2]),
                )
            ],
        }
        for p in (a, b)
    ]
    return {
        "endpoints": endpoints,
        "estimated_absolute_gradient": round(abs(zb - za), 6),
        "world_samples": samples,
        "interpretation": (
            "tile XY uses voxel centres; iso-surface Z is an estimate "
            "with unresolved sample origin. Not a collision raycast."
        ),
    }


def probe_tile_world(
    database: SaveDatabase,
    tile: str | Path,
    *,
    world_id: int,
    node_id: int,
    edge: tuple[str, str] | None = None,
    density_bits: int = 5,
    tolerance_m: float = 1.0,
    limit: int = 5000,
) -> dict[str, object]:
    if world_id < 1 or node_id < 1:
        raise ValueError("world_id and node_id must be positive")
    if density_bits not in (4, 5):
        raise ValueError("density_bits must be 4 or 5")
    if not isfinite(tolerance_m) or not 0 < tolerance_m <= 10:
        raise ValueError("tolerance_m must be > 0 and <= 10")

    path = Path(tile).expanduser().resolve()
    header = probe_tile(path)
    tile_uuid = str(UUID(hex=header["uuid_hex"]))
    dimensions = _dimensions(path)
    topology = build_layout_topology(database, world_id=world_id, limit=limit)
    node = next((n for n in topology.nodes if n.node_id == node_id), None)
    if node is None:
        raise ValueError(f"layout node {node_id} not found in world {world_id}")
    _verify_placement(node, dimensions, tile_uuid)

    sockets = []
    for chunk in probe_tile_nodes(path)["node_chunks"]:
        for record in chunk["nodes"]:
            pos = tuple(float(v) for v in record["tile_position"])
            transformed = tile_to_world(node, dimensions, pos)
            sockets.append({
                "socket": f"cell{chunk['cell']}:node{record['index']}",
                "tile_position": tuple(round(v, 6) for v in pos),
                "world_position": tuple(round(v, 6) for v in transformed),
            })
    _, terrain = _load_terrain_table(database, world_id=world_id, limit=limit)
    matches = _match_saved_tunnels(
        sockets, _extract_tunnels(terrain), tolerance_m=tolerance_m,
    )
    unique_sockets = {item["socket"] for item in matches}
    unique_tunnels = {item["tunnel_id"] for item in matches}
    independently_aligned = len(unique_sockets) >= 2 and len(unique_tunnels) >= 2

    result = {
        "world_id": world_id,
        "node_id": node_id,
        "tile": str(path),
        "tile_uuid": tile_uuid,
        "tile_name": node.name,
        "tile_dimensions_m": dimensions,
        "layout_kind": node.kind,
        "layout_rotation_quarter_turns": node.rotation & 3,
        "world_bounds": {
            "min": (node.min_x, node.min_y, node.min_z),
            "max": (node.max_x, node.max_y, node.max_z),
        },
        "sockets": sockets,
        "saved_tunnel_matches": matches,
        "match_tolerance_m": tolerance_m,
        "alignment": {
            "status": (
                "two_or_more_independent_tunnel_anchors"
                if independently_aligned
                else "insufficient_independent_tunnel_anchors"
            ),
            "distinct_sockets": len(unique_sockets),
            "distinct_tunnels": len(unique_tunnels),
            "max_match_residual_m": max(
                (item["residual_m"] for item in matches), default=None,
            ),
            "note": (
                "Validates the saved layout placement against saved tunnel "
                "endpoints, not against live in-game World coordinates"
            ),
        },
    }

    if edge is not None:
        parsed = tuple(_parse_edge_coordinate(value) for value in edge)
        volume, unknown = _load_density_bytes(path, dimensions)
        if unknown:
            raise ValueError(
                "cannot generate complete edge samples with unknown voxels"
            )
        result["critical_edge"] = _edge_measurement_samples(
            node, dimensions, volume, parsed,
            density_bits=density_bits,
            density_threshold=1 << (density_bits - 1),
        )
    return result
