from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import sqrt

from .database import SaveDatabase
from .underground_features import extract_caves, extract_pockets
from .underground_layout import (
    _dimensions_from_name,
    reconstruct_logical_structures,
)
from .underground_pockets import reconstruct_logical_pockets
from .underground_topology import LayoutNode, _nearest_layout_node
from .underground_tunnels import _extract_tunnels, _load_terrain_table

_EPSILON = 1e-6


@dataclass(frozen=True)
class ObservedPortal:
    tunnel_id: int
    side: str
    node_id: int
    tile_name: str
    family: str
    tags: tuple[str, ...]
    rotation: int
    method: str
    nearest_face: str
    nearest_face_distance: float
    world_face: str
    ray_distance: float
    canonical_face: str
    canonical_u: float
    canonical_v: float
    endpoint_x: float
    endpoint_y: float
    endpoint_z: float
    portal_x: float
    portal_y: float
    portal_z: float

    def to_dict(self) -> dict[str, object]:
        return {
            "tunnel_id": self.tunnel_id,
            "side": self.side,
            "node_id": self.node_id,
            "tile_name": self.tile_name,
            "family": self.family,
            "tags": list(self.tags),
            "rotation": self.rotation,
            "method": self.method,
            "nearest_face": self.nearest_face,
            "nearest_face_distance": round(
                self.nearest_face_distance,
                6,
            ),
            "world_face": self.world_face,
            "ray_distance": round(self.ray_distance, 6),
            "canonical_face": self.canonical_face,
            "canonical_u": round(self.canonical_u, 6),
            "canonical_v": round(self.canonical_v, 6),
            "endpoint": {
                "x": round(self.endpoint_x, 6),
                "y": round(self.endpoint_y, 6),
                "z": round(self.endpoint_z, 6),
            },
            "portal": {
                "x": round(self.portal_x, 6),
                "y": round(self.portal_y, 6),
                "z": round(self.portal_z, 6),
            },
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
        (32.0, "<=32m"),
    )

    for limit, label in limits:
        if distance <= limit:
            return label

    return ">32m"


def _endpoint_direction(
    points: list[tuple[float, float, float]],
    side: str,
) -> tuple[float, float, float] | None:
    if len(points) < 2:
        return None

    endpoint = points[0] if side == "start" else points[-1]
    candidates = points[1:] if side == "start" else reversed(points[:-1])

    for candidate in candidates:
        dx = float(candidate[0] - endpoint[0])
        dy = float(candidate[1] - endpoint[1])
        dz = float(candidate[2] - endpoint[2])
        length = sqrt(dx * dx + dy * dy + dz * dz)

        if length <= _EPSILON:
            continue

        return dx / length, dy / length, dz / length

    return None


def _point_inside(
    point: tuple[float, float, float],
    node: LayoutNode,
) -> bool:
    x, y, z = point
    return (
        node.min_x - _EPSILON <= x <= node.max_x + _EPSILON
        and node.min_y - _EPSILON <= y <= node.max_y + _EPSILON
        and node.min_z - _EPSILON <= z <= node.max_z + _EPSILON
    )


def _line_box_intersections(
    point: tuple[float, float, float],
    direction: tuple[float, float, float],
    node: LayoutNode,
    *,
    forward_only: bool,
) -> list[
    tuple[
        float,
        str,
        tuple[float, float, float],
    ]
]:
    px, py, pz = point
    dx, dy, dz = direction
    bounds = (
        ("x-", 0, node.min_x),
        ("x+", 0, node.max_x),
        ("y-", 1, node.min_y),
        ("y+", 1, node.max_y),
        ("z-", 2, node.min_z),
        ("z+", 2, node.max_z),
    )
    p = (px, py, pz)
    d = (dx, dy, dz)
    candidates = []

    for face, axis, plane in bounds:
        component = d[axis]
        if abs(component) <= _EPSILON:
            continue

        t = (plane - p[axis]) / component
        if forward_only and t < -_EPSILON:
            continue

        q = (
            px + t * dx,
            py + t * dy,
            pz + t * dz,
        )

        if not (
            node.min_x - _EPSILON <= q[0] <= node.max_x + _EPSILON
            and node.min_y - _EPSILON <= q[1] <= node.max_y + _EPSILON
            and node.min_z - _EPSILON <= q[2] <= node.max_z + _EPSILON
        ):
            continue

        distance = abs(t)
        candidates.append((distance, face, q))

    candidates.sort(
        key=lambda item: (
            item[0],
            item[1],
        )
    )
    return candidates


def _ray_exit(
    point: tuple[float, float, float],
    direction: tuple[float, float, float],
    node: LayoutNode,
) -> tuple[
    str,
    float,
    tuple[float, float, float],
    str,
] | None:
    inside = _point_inside(point, node)
    candidates = _line_box_intersections(
        point,
        direction,
        node,
        forward_only=inside,
    )

    if candidates:
        distance, face, intersection = candidates[0]
        return (
            face,
            distance,
            intersection,
            "ray" if inside else "line",
        )

    # The tangent may be noisy for an endpoint just outside the logical
    # volume. Try the same geometric line in the opposite direction before
    # falling back to the old nearest-face projection.
    reverse = tuple(-value for value in direction)
    candidates = _line_box_intersections(
        point,
        reverse,
        node,
        forward_only=False,
    )

    if candidates:
        distance, face, intersection = candidates[0]
        return face, distance, intersection, "line-reverse"

    return None


def _canonical_point(
    node: LayoutNode,
    point: tuple[float, float, float],
) -> tuple[float, float, float] | None:
    dimensions = _dimensions_from_name(node.name)
    if dimensions is None:
        return None

    width = dimensions[0] * 16.0
    depth = dimensions[1] * 16.0
    wx = point[0] - node.min_x
    wy = point[1] - node.min_y
    wz = point[2] - node.min_z
    rotation = node.rotation & 3

    if rotation == 1:
        lx = wy
        ly = depth - wx
    elif rotation == 2:
        lx = width - wx
        ly = depth - wy
    elif rotation == 3:
        lx = width - wy
        ly = wx
    else:
        lx = wx
        ly = wy

    return lx, ly, wz


def _canonical_face_uv(
    node: LayoutNode,
    point: tuple[float, float, float],
) -> tuple[str, float, float] | None:
    local = _canonical_point(node, point)
    dimensions = _dimensions_from_name(node.name)

    if local is None or dimensions is None:
        return None

    x, y, z = local
    width = dimensions[0] * 16.0
    depth = dimensions[1] * 16.0
    height = dimensions[2] * 16.0

    candidates = [
        ("x-", abs(x), y, z),
        ("x+", abs(width - x), y, z),
        ("y-", abs(y), x, z),
        ("y+", abs(depth - y), x, z),
        ("z-", abs(z), x, y),
        ("z+", abs(height - z), x, y),
    ]
    face, _, u, v = min(
        candidates,
        key=lambda item: (
            item[1],
            item[0],
        ),
    )
    return face, u, v


def _rounded_portal_key(
    portal: ObservedPortal,
    *,
    step: float = 4.0,
) -> tuple[str, float, float]:
    return (
        portal.canonical_face,
        round(portal.canonical_u / step) * step,
        round(portal.canonical_v / step) * step,
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
        points = tunnel["points"]
        endpoints = (
            ("start", points[0]),
            ("end", points[-1]),
        )

        for side, point in endpoints:
            node = _nearest_layout_node(
                point,
                nodes,
                tolerance=attach_tolerance,
            )
            if node is None:
                continue

            direction = _endpoint_direction(points, side)
            if direction is None:
                continue

            nearest_face, nearest_distance, _, _ = _nearest_face(
                point,
                node,
            )

            ray = _ray_exit(
                point,
                direction,
                node,
            )

            if ray is None:
                # Preserve an observation rather than silently dropping it,
                # but mark that it came from the weaker nearest-face fallback.
                world_face, _, _, _ = _nearest_face(point, node)
                portal_point = point
                ray_distance = nearest_distance
                method = "nearest-fallback"
            else:
                (
                    world_face,
                    ray_distance,
                    portal_point,
                    method,
                ) = ray

            canonical = _canonical_face_uv(
                node,
                portal_point,
            )
            if canonical is None:
                continue

            canonical_face, canonical_u, canonical_v = canonical

            portals.append(
                ObservedPortal(
                    tunnel_id=int(tunnel["id"]),
                    side=side,
                    node_id=node.node_id,
                    tile_name=node.name,
                    family=node.family,
                    tags=node.tags,
                    rotation=node.rotation,
                    method=method,
                    nearest_face=nearest_face,
                    nearest_face_distance=nearest_distance,
                    world_face=world_face,
                    ray_distance=ray_distance,
                    canonical_face=canonical_face,
                    canonical_u=canonical_u,
                    canonical_v=canonical_v,
                    endpoint_x=float(point[0]),
                    endpoint_y=float(point[1]),
                    endpoint_z=float(point[2]),
                    portal_x=float(portal_point[0]),
                    portal_y=float(portal_point[1]),
                    portal_z=float(portal_point[2]),
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

    node_lookup = {
        node.node_id: node
        for node in nodes
    }

    method_counts = Counter(portal.method for portal in portals)
    world_face_counts = Counter(portal.world_face for portal in portals)
    canonical_face_counts = Counter(
        portal.canonical_face
        for portal in portals
    )
    ray_distance_buckets = Counter(
        _distance_bucket(portal.ray_distance)
        for portal in portals
    )
    nearest_distance_buckets = Counter(
        _distance_bucket(portal.nearest_face_distance)
        for portal in portals
    )
    role_counts = Counter(
        node_lookup[portal.node_id].semantic_role
        for portal in portals
    )

    grouped: dict[str, list[ObservedPortal]] = defaultdict(list)
    for portal in portals:
        grouped[portal.tile_name].append(portal)

    profiles = []

    for tile_name, group in grouped.items():
        node_ids = {portal.node_id for portal in group}
        rotations = Counter(portal.rotation for portal in group)
        canonical_faces = Counter(
            portal.canonical_face
            for portal in group
        )
        rounded = Counter(
            _rounded_portal_key(portal)
            for portal in group
        )
        placement_support: dict[
            tuple[str, float, float],
            set[int],
        ] = defaultdict(set)

        for portal in group:
            placement_support[
                _rounded_portal_key(portal)
            ].add(portal.node_id)

        clusters = []
        for key, count in rounded.items():
            face, u, v = key
            placements = len(placement_support[key])
            clusters.append(
                {
                    "face": face,
                    "u": u,
                    "v": v,
                    "count": count,
                    "placements": placements,
                }
            )

        clusters.sort(
            key=lambda item: (
                -item["placements"],
                -item["count"],
                item["face"],
                item["u"],
                item["v"],
            )
        )

        sample = group[0]
        profiles.append(
            {
                "tile_name": tile_name,
                "family": sample.family,
                "tags": list(sample.tags),
                "placements_with_endpoints": len(node_ids),
                "endpoints": len(group),
                "rotations": dict(
                    sorted(rotations.items())
                ),
                "canonical_faces": dict(
                    canonical_faces.most_common()
                ),
                "portal_clusters_4m": clusters[:20],
                "repeated_clusters_4m": [
                    cluster
                    for cluster in clusters
                    if cluster["placements"] >= 2
                ][:20],
            }
        )

    profiles.sort(
        key=lambda profile: (
            -profile["placements_with_endpoints"],
            -profile["endpoints"],
            profile["tile_name"],
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
        "methods": dict(method_counts.most_common()),
        "world_faces": dict(world_face_counts.most_common()),
        "canonical_faces": dict(
            canonical_face_counts.most_common()
        ),
        "ray_distance_buckets": dict(ray_distance_buckets),
        "nearest_distance_buckets": dict(
            nearest_distance_buckets
        ),
        "endpoint_roles": dict(role_counts.most_common()),
        "profiles": profiles[:top],
        "furthest_ray_examples": [
            portal.to_dict()
            for portal in sorted(
                portals,
                key=lambda portal: (
                    -portal.ray_distance,
                    portal.tunnel_id,
                    portal.side,
                ),
            )[:10]
        ],
    }
