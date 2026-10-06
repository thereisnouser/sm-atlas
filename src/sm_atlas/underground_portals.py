from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import sqrt
from typing import Iterable

from .database import SaveDatabase
from .underground_features import extract_caves, extract_pockets
from .underground_layout import (
    _dimensions_from_name,
    reconstruct_logical_structures,
)
from .underground_pockets import reconstruct_logical_pockets
from .underground_topology import LayoutNode, _nearest_layout_node
from .underground_tunnels import _extract_tunnels, _load_terrain_table


@dataclass(frozen=True)
class ObservedPortal:
    tunnel_id: int
    side: str
    node_id: int
    tile_name: str
    family: str
    tags: tuple[str, ...]
    rotation: int
    face: str
    face_distance: float
    u: float
    v: float
    x: float
    y: float
    z: float

    def to_dict(self) -> dict[str, object]:
        return {
            "tunnel_id": self.tunnel_id,
            "side": self.side,
            "node_id": self.node_id,
            "tile_name": self.tile_name,
            "family": self.family,
            "tags": list(self.tags),
            "rotation": self.rotation,
            "face": self.face,
            "face_distance": round(self.face_distance, 6),
            "u": round(self.u, 6),
            "v": round(self.v, 6),
            "x": round(self.x, 6),
            "y": round(self.y, 6),
            "z": round(self.z, 6),
        }


def _node_for_structure(node_id: int, structure) -> LayoutNode:
    return LayoutNode(
        node_id=node_id,
        kind="structure",
        name=structure.name,
        family=structure.family,
        tags=(),
        min_x=structure.min_x,
        max_x=structure.max_x,
        min_y=structure.min_y,
        max_y=structure.max_y,
        min_z=structure.min_z,
        max_z=structure.max_z,
        tile_uuid=structure.tile_uuid,
        rotation=structure.rotation,
    )


def _node_for_pocket(node_id: int, placement) -> LayoutNode:
    return LayoutNode(
        node_id=node_id,
        kind="pocket",
        name=placement.name,
        family=placement.family,
        tags=placement.tags,
        min_x=placement.min_x,
        max_x=placement.max_x,
        min_y=placement.min_y,
        max_y=placement.max_y,
        min_z=placement.min_z,
        max_z=placement.max_z,
        tile_uuid=placement.tile_uuid,
        rotation=placement.rotation,
    )


def _build_nodes(value: dict) -> list[LayoutNode]:
    caves = extract_caves(value)
    pockets = extract_pockets(value)
    structures = reconstruct_logical_structures(caves)
    logical_pockets = reconstruct_logical_pockets(
        pockets,
        _dimensions_from_name,
    )

    nodes: list[LayoutNode] = []

    for structure in structures:
        nodes.append(
            _node_for_structure(
                len(nodes) + 1,
                structure,
            )
        )

    for placement in logical_pockets:
        nodes.append(
            _node_for_pocket(
                len(nodes) + 1,
                placement,
            )
        )

    return nodes


def _nearest_face(
    point: tuple[float, float, float],
    node: LayoutNode,
) -> tuple[str, float, float, float]:
    x, y, z = point
    candidates = [
        (
            "x-",
            abs(x - node.min_x),
            y - node.min_y,
            z - node.min_z,
        ),
        (
            "x+",
            abs(node.max_x - x),
            y - node.min_y,
            z - node.min_z,
        ),
        (
            "y-",
            abs(y - node.min_y),
            x - node.min_x,
            z - node.min_z,
        ),
        (
            "y+",
            abs(node.max_y - y),
            x - node.min_x,
            z - node.min_z,
        ),
        (
            "z-",
            abs(z - node.min_z),
            x - node.min_x,
            y - node.min_y,
        ),
        (
            "z+",
            abs(node.max_z - z),
            x - node.min_x,
            y - node.min_y,
        ),
    ]

    return min(
        candidates,
        key=lambda item: (
            item[1],
            item[0],
        ),
    )


def _distance_bucket(distance: float) -> str:
    limits = (
        (0.5, "<=0.5m"),
        (1.0, "<=1m"),
        (2.0, "<=2m"),
        (4.0, "<=4m"),
        (8.0, "<=8m"),
        (16.0, "<=16m"),
    )

    for limit, label in limits:
        if distance <= limit:
            return label

    return ">16m"


def _rounded_portal_key(
    portal: ObservedPortal,
    *,
    step: float = 4.0,
) -> tuple[str, float, float]:
    return (
        portal.face,
        round(portal.u / step) * step,
        round(portal.v / step) * step,
    )


def observe_saved_tunnel_portals(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
    attach_tolerance: float = 4.0,
) -> tuple[list[LayoutNode], list[ObservedPortal]]:
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    if not 0.0 <= attach_tolerance <= 64.0:
        raise ValueError("attach_tolerance must be between 0 and 64")

    _, value = _load_terrain_table(
        database,
        world_id=world_id,
        limit=limit,
    )

    nodes = _build_nodes(value)
    tunnels = _extract_tunnels(value)
    portals: list[ObservedPortal] = []

    for tunnel in tunnels:
        endpoints = (
            ("start", tunnel["points"][0]),
            ("end", tunnel["points"][-1]),
        )

        for side, point in endpoints:
            node = _nearest_layout_node(
                point,
                nodes,
                tolerance=attach_tolerance,
            )
            if node is None:
                continue

            face, face_distance, u, v = _nearest_face(
                point,
                node,
            )

            portals.append(
                ObservedPortal(
                    tunnel_id=int(tunnel["id"]),
                    side=side,
                    node_id=node.node_id,
                    tile_name=node.name,
                    family=node.family,
                    tags=node.tags,
                    rotation=node.rotation,
                    face=face,
                    face_distance=face_distance,
                    u=u,
                    v=v,
                    x=float(point[0]),
                    y=float(point[1]),
                    z=float(point[2]),
                )
            )

    return nodes, portals


def summarize_saved_tunnel_portals(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
    attach_tolerance: float = 4.0,
    top: int = 30,
) -> dict[str, object]:
    if not 1 <= top <= 200:
        raise ValueError("top must be between 1 and 200")

    nodes, portals = observe_saved_tunnel_portals(
        database,
        world_id=world_id,
        limit=limit,
        attach_tolerance=attach_tolerance,
    )

    face_counts = Counter(portal.face for portal in portals)
    distance_buckets = Counter(
        _distance_bucket(portal.face_distance)
        for portal in portals
    )
    role_counts = Counter()

    node_lookup = {
        node.node_id: node
        for node in nodes
    }

    for portal in portals:
        role_counts[node_lookup[portal.node_id].semantic_role] += 1

    grouped: dict[
        tuple[str, int],
        list[ObservedPortal],
    ] = defaultdict(list)

    for portal in portals:
        grouped[(portal.tile_name, portal.rotation)].append(portal)

    profiles = []

    for (tile_name, rotation), group in grouped.items():
        node_ids = {portal.node_id for portal in group}
        faces = Counter(portal.face for portal in group)
        rounded = Counter(
            _rounded_portal_key(portal)
            for portal in group
        )
        distances = [
            portal.face_distance
            for portal in group
        ]

        sample = group[0]
        profiles.append(
            {
                "tile_name": tile_name,
                "family": sample.family,
                "tags": list(sample.tags),
                "rotation": rotation,
                "placements_with_endpoints": len(node_ids),
                "endpoints": len(group),
                "faces": dict(faces.most_common()),
                "portal_clusters_4m": [
                    {
                        "face": face,
                        "u": u,
                        "v": v,
                        "count": count,
                    }
                    for (face, u, v), count in rounded.most_common(12)
                ],
                "face_distance": {
                    "min": round(min(distances), 6),
                    "max": round(max(distances), 6),
                    "avg": round(
                        sum(distances) / len(distances),
                        6,
                    ),
                },
            }
        )

    profiles.sort(
        key=lambda profile: (
            -profile["endpoints"],
            profile["tile_name"],
            profile["rotation"],
        )
    )

    node_endpoint_counts = Counter(
        portal.node_id
        for portal in portals
    )

    nodes_with_endpoints = [
        node
        for node in nodes
        if node_endpoint_counts[node.node_id] > 0
    ]

    return {
        "world_id": world_id,
        "logical_nodes": len(nodes),
        "observed_endpoints": len(portals),
        "nodes_with_endpoints": len(nodes_with_endpoints),
        "face_counts": dict(face_counts.most_common()),
        "distance_buckets": dict(distance_buckets),
        "endpoint_roles": dict(role_counts.most_common()),
        "profiles": profiles[:top],
        "closest_examples": [
            portal.to_dict()
            for portal in sorted(
                portals,
                key=lambda portal: (
                    portal.face_distance,
                    portal.tunnel_id,
                    portal.side,
                ),
            )[:10]
        ],
        "furthest_examples": [
            portal.to_dict()
            for portal in sorted(
                portals,
                key=lambda portal: (
                    -portal.face_distance,
                    portal.tunnel_id,
                    portal.side,
                ),
            )[:10]
        ],
    }
