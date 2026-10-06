from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import sqrt
from typing import Any

from .database import SaveDatabase
from .underground_features import (
    UndergroundPiece,
    UndergroundSpawner,
    extract_caves,
    extract_pockets,
    extract_spawners,
)
from .underground_tunnels import _extract_tunnels, _load_terrain_table

DEFAULT_REGION_TOLERANCE = 4.0
DEFAULT_ENDPOINT_TOLERANCE = 6.0
_OVERLAP_EPSILON = 1e-6


@dataclass(frozen=True)
class UndergroundRegion:
    region_id: int
    pieces: tuple[UndergroundPiece, ...]
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    min_z: float
    max_z: float

    @property
    def center(self) -> tuple[float, float, float]:
        return (
            (self.min_x + self.max_x) / 2.0,
            (self.min_y + self.max_y) / 2.0,
            (self.min_z + self.max_z) / 2.0,
        )

    @property
    def cave_count(self) -> int:
        return sum(piece.kind == "cave" for piece in self.pieces)

    @property
    def pocket_count(self) -> int:
        return sum(piece.kind == "pocket" for piece in self.pieces)

    def to_dict(self) -> dict[str, object]:
        x, y, z = self.center
        return {
            "id": self.region_id,
            "center": {"x": x, "y": y, "z": z},
            "bounds": {
                "min_x": self.min_x,
                "max_x": self.max_x,
                "min_y": self.min_y,
                "max_y": self.max_y,
                "min_z": self.min_z,
                "max_z": self.max_z,
            },
            "pieces": len(self.pieces),
            "caves": self.cave_count,
            "pockets": self.pocket_count,
        }


@dataclass(frozen=True)
class UndergroundGraphNode:
    node_id: int
    kind: str
    x: float
    y: float
    z: float
    region_id: int | None
    cave_count: int
    pocket_count: int
    spawner_count: int

    def to_dict(self, *, degree: int) -> dict[str, object]:
        return {
            "id": self.node_id,
            "kind": self.kind,
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "z": round(self.z, 3),
            "region_id": self.region_id,
            "degree": degree,
            "caves": self.cave_count,
            "pockets": self.pocket_count,
            "spawners": self.spawner_count,
        }


@dataclass(frozen=True)
class UndergroundGraphEdge:
    tunnel_id: int
    tunnel_type: str
    start_node: int
    end_node: int
    length: float

    def to_dict(self) -> dict[str, object]:
        return {
            "tunnel_id": self.tunnel_id,
            "tunnel_type": self.tunnel_type,
            "start_node": self.start_node,
            "end_node": self.end_node,
            "length": round(self.length, 3),
        }


@dataclass(frozen=True)
class UndergroundGraph:
    world_id: int
    regions: tuple[UndergroundRegion, ...]
    nodes: tuple[UndergroundGraphNode, ...]
    edges: tuple[UndergroundGraphEdge, ...]
    region_endpoint_count: int
    free_endpoint_count: int
    attached_spawners: int
    unattached_spawners: int

    def _degrees(self) -> dict[int, int]:
        degrees = {node.node_id: 0 for node in self.nodes}

        for edge in self.edges:
            if edge.start_node == edge.end_node:
                degrees[edge.start_node] += 2
                continue

            degrees[edge.start_node] += 1
            degrees[edge.end_node] += 1

        return degrees

    def _components(self) -> list[list[int]]:
        adjacency = {
            node.node_id: set()
            for node in self.nodes
        }

        for edge in self.edges:
            adjacency[edge.start_node].add(edge.end_node)
            adjacency[edge.end_node].add(edge.start_node)

        remaining = set(adjacency)
        components: list[list[int]] = []

        while remaining:
            start = min(remaining)
            stack = [start]
            component: list[int] = []
            remaining.remove(start)

            while stack:
                node_id = stack.pop()
                component.append(node_id)

                for neighbor in adjacency[node_id]:
                    if neighbor not in remaining:
                        continue
                    remaining.remove(neighbor)
                    stack.append(neighbor)

            components.append(sorted(component))

        components.sort(key=lambda component: (-len(component), component[0]))
        return components

    def summary(self, *, top_hubs: int = 10) -> dict[str, object]:
        degrees = self._degrees()
        components = self._components()
        node_kinds = Counter(node.kind for node in self.nodes)
        degree_histogram = Counter(degrees.values())
        tunnel_types = Counter(edge.tunnel_type for edge in self.edges)

        self_loops = sum(
            edge.start_node == edge.end_node
            for edge in self.edges
        )
        isolated_nodes = sum(
            degree == 0
            for degree in degrees.values()
        )
        dead_ends = sum(
            degree == 1
            for degree in degrees.values()
        )

        node_lookup = {
            node.node_id: node
            for node in self.nodes
        }
        hubs = sorted(
            self.nodes,
            key=lambda node: (
                -degrees[node.node_id],
                node.node_id,
            ),
        )[:top_hubs]

        return {
            "world_id": self.world_id,
            "regions": len(self.regions),
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "node_kinds": dict(node_kinds.most_common()),
            "tunnel_types": dict(tunnel_types.most_common()),
            "region_endpoints": self.region_endpoint_count,
            "free_endpoints": self.free_endpoint_count,
            "attached_spawners": self.attached_spawners,
            "unattached_spawners": self.unattached_spawners,
            "connected_components": len(components),
            "largest_component_nodes": (
                len(components[0])
                if components
                else 0
            ),
            "isolated_nodes": isolated_nodes,
            "dead_ends": dead_ends,
            "self_loops": self_loops,
            "degree_histogram": dict(
                sorted(degree_histogram.items())
            ),
            "top_hubs": [
                node_lookup[node.node_id].to_dict(
                    degree=degrees[node.node_id]
                )
                for node in hubs
            ],
        }

    def to_dict(self) -> dict[str, object]:
        degrees = self._degrees()
        return {
            **self.summary(),
            "region_data": [
                region.to_dict()
                for region in self.regions
            ],
            "node_data": [
                node.to_dict(degree=degrees[node.node_id])
                for node in self.nodes
            ],
            "edge_data": [
                edge.to_dict()
                for edge in self.edges
            ],
        }


class _DisjointSet:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)

        if left_root == right_root:
            return

        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root

        self.parent[right_root] = left_root

        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1


def _axis_overlap(
    left_min: float,
    left_max: float,
    right_min: float,
    right_max: float,
) -> float:
    return min(left_max, right_max) - max(left_min, right_min)


def _pieces_overlap(
    left: UndergroundPiece,
    right: UndergroundPiece,
) -> bool:
    return (
        _axis_overlap(left.x, left.max_x, right.x, right.max_x)
        > _OVERLAP_EPSILON
        and _axis_overlap(left.y, left.max_y, right.y, right.max_y)
        > _OVERLAP_EPSILON
        and _axis_overlap(left.z, left.max_z, right.z, right.max_z)
        > _OVERLAP_EPSILON
    )


def cluster_underground_regions(
    pieces: list[UndergroundPiece],
) -> list[UndergroundRegion]:
    if not pieces:
        return []

    dsu = _DisjointSet(len(pieces))

    for left_index, left in enumerate(pieces):
        for right_index in range(left_index + 1, len(pieces)):
            right = pieces[right_index]
            if _pieces_overlap(left, right):
                dsu.union(left_index, right_index)

    groups: dict[int, list[UndergroundPiece]] = {}

    for index, piece in enumerate(pieces):
        root = dsu.find(index)
        groups.setdefault(root, []).append(piece)

    ordered_groups = sorted(
        groups.values(),
        key=lambda group: (
            min(piece.z for piece in group),
            min(piece.y for piece in group),
            min(piece.x for piece in group),
            len(group),
        ),
    )

    regions: list[UndergroundRegion] = []

    for region_id, group in enumerate(ordered_groups, start=1):
        regions.append(
            UndergroundRegion(
                region_id=region_id,
                pieces=tuple(group),
                min_x=min(piece.x for piece in group),
                max_x=max(piece.max_x for piece in group),
                min_y=min(piece.y for piece in group),
                max_y=max(piece.max_y for piece in group),
                min_z=min(piece.z for piece in group),
                max_z=max(piece.max_z for piece in group),
            )
        )

    return regions


def _axis_distance(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    if value < minimum:
        return minimum - value
    if value > maximum:
        return value - maximum
    return 0.0


def _point_piece_distance(
    point: tuple[float, float, float],
    piece: UndergroundPiece,
) -> float:
    x, y, z = point
    dx = _axis_distance(x, piece.x, piece.max_x)
    dy = _axis_distance(y, piece.y, piece.max_y)
    dz = _axis_distance(z, piece.z, piece.max_z)
    return sqrt(dx * dx + dy * dy + dz * dz)


def _point_region_distance(
    point: tuple[float, float, float],
    region: UndergroundRegion,
) -> float:
    return min(
        _point_piece_distance(point, piece)
        for piece in region.pieces
    )


def _nearest_region(
    point: tuple[float, float, float],
    regions: list[UndergroundRegion],
    *,
    tolerance: float,
) -> UndergroundRegion | None:
    best_region = None
    best_distance = tolerance

    for region in regions:
        distance = _point_region_distance(point, region)

        if distance > best_distance:
            continue

        if (
            best_region is None
            or distance < best_distance
            or region.region_id < best_region.region_id
        ):
            best_region = region
            best_distance = distance

    return best_region


def _point_distance(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    dx = right[0] - left[0]
    dy = right[1] - left[1]
    dz = right[2] - left[2]
    return sqrt(dx * dx + dy * dy + dz * dz)


def _cluster_free_endpoints(
    endpoints: list[tuple[int, str, tuple[float, float, float]]],
    *,
    tolerance: float,
) -> list[list[int]]:
    if not endpoints:
        return []

    dsu = _DisjointSet(len(endpoints))

    for left_index, left in enumerate(endpoints):
        for right_index in range(left_index + 1, len(endpoints)):
            right = endpoints[right_index]
            if _point_distance(left[2], right[2]) <= tolerance:
                dsu.union(left_index, right_index)

    groups: dict[int, list[int]] = {}
    for index in range(len(endpoints)):
        root = dsu.find(index)
        groups.setdefault(root, []).append(index)

    return sorted(
        groups.values(),
        key=lambda group: (
            min(endpoints[index][2][2] for index in group),
            min(endpoints[index][2][1] for index in group),
            min(endpoints[index][2][0] for index in group),
        ),
    )


def _attach_spawners(
    spawners: list[UndergroundSpawner],
    regions: list[UndergroundRegion],
    *,
    tolerance: float,
) -> tuple[dict[int, int], int]:
    counts: dict[int, int] = {}
    unattached = 0

    for spawner in spawners:
        region = _nearest_region(
            (spawner.x, spawner.y, spawner.z),
            regions,
            tolerance=tolerance,
        )

        if region is None:
            unattached += 1
            continue

        counts[region.region_id] = counts.get(region.region_id, 0) + 1

    return counts, unattached


def build_underground_graph(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
    region_tolerance: float = DEFAULT_REGION_TOLERANCE,
    endpoint_tolerance: float = DEFAULT_ENDPOINT_TOLERANCE,
) -> UndergroundGraph:
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    if not 0.0 <= region_tolerance <= 64.0:
        raise ValueError("region_tolerance must be between 0 and 64")
    if not 0.0 <= endpoint_tolerance <= 64.0:
        raise ValueError("endpoint_tolerance must be between 0 and 64")

    _, value = _load_terrain_table(
        database,
        world_id=world_id,
        limit=limit,
    )

    tunnels = _extract_tunnels(value)
    caves = extract_caves(value)
    pockets = extract_pockets(value)
    spawners = extract_spawners(value)

    regions = cluster_underground_regions(caves + pockets)
    spawner_counts, unattached_spawners = _attach_spawners(
        spawners,
        regions,
        tolerance=region_tolerance,
    )

    nodes: list[UndergroundGraphNode] = []
    region_nodes: dict[int, int] = {}

    for region in regions:
        node_id = len(nodes) + 1
        x, y, z = region.center
        nodes.append(
            UndergroundGraphNode(
                node_id=node_id,
                kind="region",
                x=x,
                y=y,
                z=z,
                region_id=region.region_id,
                cave_count=region.cave_count,
                pocket_count=region.pocket_count,
                spawner_count=spawner_counts.get(region.region_id, 0),
            )
        )
        region_nodes[region.region_id] = node_id

    endpoint_nodes: dict[tuple[int, str], int] = {}
    free_endpoints: list[
        tuple[int, str, tuple[float, float, float]]
    ] = []
    region_endpoint_count = 0

    for tunnel in tunnels:
        endpoints = (
            ("start", tunnel["points"][0]),
            ("end", tunnel["points"][-1]),
        )

        for side, point in endpoints:
            region = _nearest_region(
                point,
                regions,
                tolerance=region_tolerance,
            )

            if region is not None:
                endpoint_nodes[(tunnel["id"], side)] = (
                    region_nodes[region.region_id]
                )
                region_endpoint_count += 1
                continue

            free_endpoints.append((tunnel["id"], side, point))

    free_groups = _cluster_free_endpoints(
        free_endpoints,
        tolerance=endpoint_tolerance,
    )

    for group in free_groups:
        points = [free_endpoints[index][2] for index in group]
        node_id = len(nodes) + 1
        kind = "junction" if len(group) > 1 else "terminal"

        nodes.append(
            UndergroundGraphNode(
                node_id=node_id,
                kind=kind,
                x=sum(point[0] for point in points) / len(points),
                y=sum(point[1] for point in points) / len(points),
                z=sum(point[2] for point in points) / len(points),
                region_id=None,
                cave_count=0,
                pocket_count=0,
                spawner_count=0,
            )
        )

        for index in group:
            tunnel_id, side, _ = free_endpoints[index]
            endpoint_nodes[(tunnel_id, side)] = node_id

    edges: list[UndergroundGraphEdge] = []

    for tunnel in tunnels:
        start_node = endpoint_nodes[(tunnel["id"], "start")]
        end_node = endpoint_nodes[(tunnel["id"], "end")]

        edges.append(
            UndergroundGraphEdge(
                tunnel_id=tunnel["id"],
                tunnel_type=tunnel["type"],
                start_node=start_node,
                end_node=end_node,
                length=float(tunnel["length"]),
            )
        )

    return UndergroundGraph(
        world_id=world_id,
        regions=tuple(regions),
        nodes=tuple(nodes),
        edges=tuple(edges),
        region_endpoint_count=region_endpoint_count,
        free_endpoint_count=len(free_endpoints),
        attached_spawners=len(spawners) - unattached_spawners,
        unattached_spawners=unattached_spawners,
    )
