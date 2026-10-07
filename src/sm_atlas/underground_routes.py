from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from math import sqrt

from .database import SaveDatabase
from .underground_navigation import TRANSIT_ROLES
from .underground_topology import (
    LayoutNode,
    LayoutTopology,
    build_layout_topology,
)


@dataclass(frozen=True)
class TransitEdge:
    left: int
    right: int
    kind: str
    weight: float
    axis: str | None = None
    tunnel_id: int | None = None
    tunnel_type: str | None = None

    def other(self, node_id: int) -> int:
        if node_id == self.left:
            return self.right
        if node_id == self.right:
            return self.left
        raise ValueError(f"node {node_id} is not part of edge")


@dataclass(frozen=True)
class TransitRoute:
    world_id: int
    include_vertical_contacts: bool
    start_node: int
    target_kind: str
    target_value: str
    target_node: int
    total_cost: float
    node_path: tuple[int, ...]
    edges: tuple[TransitEdge, ...]
    target_tunnel_id: int | None = None
    target_tunnel_type: str | None = None
    target_tunnel_length: float | None = None

    def to_dict(
        self,
        lookup: dict[int, LayoutNode],
    ) -> dict[str, object]:
        return {
            "world_id": self.world_id,
            "include_vertical_contacts": self.include_vertical_contacts,
            "start_node": self.start_node,
            "target_kind": self.target_kind,
            "target_value": self.target_value,
            "target_node": self.target_node,
            "total_cost": round(self.total_cost, 3),
            "target_tunnel": (
                None
                if self.target_tunnel_id is None
                else {
                    "id": self.target_tunnel_id,
                    "type": self.target_tunnel_type,
                    "length": round(
                        self.target_tunnel_length or 0.0,
                        3,
                    ),
                }
            ),
            "nodes": [
                {
                    "id": node_id,
                    "role": lookup[node_id].semantic_role,
                    "name": lookup[node_id].name,
                    "tags": list(lookup[node_id].tags),
                    "center": tuple(
                        round(value, 3)
                        for value in lookup[node_id].center
                    ),
                }
                for node_id in self.node_path
            ],
            "edges": [
                {
                    "from": edge.left,
                    "to": edge.right,
                    "kind": edge.kind,
                    "weight": round(edge.weight, 3),
                    "axis": edge.axis,
                    "tunnel_id": edge.tunnel_id,
                    "tunnel_type": edge.tunnel_type,
                }
                for edge in self.edges
            ],
            "edge_kinds": {
                kind: sum(
                    edge.kind == kind
                    for edge in self.edges
                )
                for kind in ("tunnel", "contact")
                if any(
                    edge.kind == kind
                    for edge in self.edges
                )
            },
        }


def _distance(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    dx = right[0] - left[0]
    dy = right[1] - left[1]
    dz = right[2] - left[2]
    return sqrt(dx * dx + dy * dy + dz * dz)


def build_transit_edges(
    topology: LayoutTopology,
    *,
    include_vertical_contacts: bool = False,
) -> tuple[set[int], list[TransitEdge]]:
    lookup = {
        node.node_id: node
        for node in topology.nodes
    }
    transit_ids = {
        node.node_id
        for node in topology.nodes
        if node.semantic_role in TRANSIT_ROLES
    }
    edges: list[TransitEdge] = []

    for link in topology.tunnel_links:
        if link.left not in transit_ids or link.right not in transit_ids:
            continue
        if link.left == link.right:
            continue

        edges.append(
            TransitEdge(
                left=link.left,
                right=link.right,
                kind="tunnel",
                weight=link.length,
                tunnel_id=link.tunnel_id,
                tunnel_type=link.tunnel_type,
            )
        )

    for contact in topology.contacts:
        if contact.left not in transit_ids or contact.right not in transit_ids:
            continue
        if contact.axis == "z" and not include_vertical_contacts:
            continue
        if contact.left == contact.right:
            continue

        edges.append(
            TransitEdge(
                left=contact.left,
                right=contact.right,
                kind="contact",
                weight=_distance(
                    lookup[contact.left].center,
                    lookup[contact.right].center,
                ),
                axis=contact.axis,
            )
        )

    return transit_ids, edges


def _adjacency(
    transit_ids: set[int],
    edges: list[TransitEdge],
) -> dict[int, list[tuple[int, TransitEdge]]]:
    adjacency = {
        node_id: []
        for node_id in transit_ids
    }

    for edge in edges:
        adjacency[edge.left].append((edge.right, edge))
        adjacency[edge.right].append((edge.left, edge))

    return adjacency


def _shortest_paths(
    start: int,
    transit_ids: set[int],
    edges: list[TransitEdge],
) -> tuple[
    dict[int, float],
    dict[int, tuple[int, TransitEdge]],
]:
    if start not in transit_ids:
        raise ValueError(
            f"start node {start} is not a transit node"
        )

    adjacency = _adjacency(transit_ids, edges)
    distances = {
        node_id: float("inf")
        for node_id in transit_ids
    }
    previous: dict[int, tuple[int, TransitEdge]] = {}
    distances[start] = 0.0
    queue: list[tuple[float, int]] = [(0.0, start)]

    while queue:
        distance, node_id = heappop(queue)
        if distance != distances[node_id]:
            continue

        for neighbor, edge in adjacency[node_id]:
            candidate = distance + edge.weight
            if candidate >= distances[neighbor]:
                continue

            distances[neighbor] = candidate
            previous[neighbor] = (node_id, edge)
            heappush(queue, (candidate, neighbor))

    return distances, previous


def _reconstruct_route(
    start: int,
    target: int,
    previous: dict[int, tuple[int, TransitEdge]],
) -> tuple[tuple[int, ...], tuple[TransitEdge, ...]]:
    if start == target:
        return (start,), ()

    nodes = [target]
    edges = []
    current = target

    while current != start:
        if current not in previous:
            raise ValueError(
                f"target node {target} is unreachable from {start}"
            )

        parent, edge = previous[current]
        edges.append(edge)
        nodes.append(parent)
        current = parent

    nodes.reverse()
    edges.reverse()
    return tuple(nodes), tuple(edges)


def _elevator_node(
    topology: LayoutTopology,
    transit_ids: set[int],
) -> int:
    elevators = [
        node.node_id
        for node in topology.nodes
        if (
            node.node_id in transit_ids
            and node.semantic_role == "elevator"
        )
    ]

    if not elevators:
        raise ValueError("no elevator transit node found")
    if len(elevators) > 1:
        raise ValueError(
            "multiple elevator nodes found; explicit start selection "
            "is not implemented yet"
        )

    return elevators[0]


def _target_tag_nodes(
    topology: LayoutTopology,
    transit_ids: set[int],
    tag: str,
) -> list[int]:
    normalized = tag.strip().lower()
    return [
        node.node_id
        for node in topology.nodes
        if (
            node.node_id in transit_ids
            and (
                normalized in {
                    value.lower()
                    for value in node.tags
                }
                or normalized in node.name.lower()
            )
        )
    ]


def find_transit_route(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
    include_vertical_contacts: bool = False,
    target_node: int | None = None,
    target_tag: str | None = None,
    target_tunnel_type: str | None = None,
) -> tuple[TransitRoute, dict[int, LayoutNode]]:
    requested = sum(
        value is not None
        for value in (
            target_node,
            target_tag,
            target_tunnel_type,
        )
    )
    if requested != 1:
        raise ValueError(
            "exactly one route target must be specified"
        )

    topology = build_layout_topology(
        database,
        world_id=world_id,
        limit=limit,
    )
    lookup = {
        node.node_id: node
        for node in topology.nodes
    }
    transit_ids, edges = build_transit_edges(
        topology,
        include_vertical_contacts=include_vertical_contacts,
    )
    start = _elevator_node(topology, transit_ids)
    distances, previous = _shortest_paths(
        start,
        transit_ids,
        edges,
    )

    target_kind: str
    target_value: str
    target: int
    target_tunnel_id = None
    target_tunnel_type_value = None
    target_tunnel_length = None

    if target_node is not None:
        if target_node not in transit_ids:
            raise ValueError(
                f"target node {target_node} is not a transit node"
            )
        if distances[target_node] == float("inf"):
            raise ValueError(
                f"target node {target_node} is unreachable "
                f"from elevator {start}"
            )
        target = target_node
        target_kind = "node"
        target_value = str(target_node)

    elif target_tag is not None:
        candidates = _target_tag_nodes(
            topology,
            transit_ids,
            target_tag,
        )
        reachable = [
            node_id
            for node_id in candidates
            if distances[node_id] < float("inf")
        ]

        if not candidates:
            available = sorted({
                tag
                for node in topology.nodes
                if node.node_id in transit_ids
                for tag in node.tags
            })
            raise ValueError(
                f"no transit nodes match tag/name {target_tag!r}; "
                f"known tags: {available}"
            )
        if not reachable:
            raise ValueError(
                f"transit nodes matching {target_tag!r} are unreachable "
                f"from elevator {start}"
            )

        target = min(
            reachable,
            key=lambda node_id: (
                distances[node_id],
                node_id,
            ),
        )
        target_kind = "tag"
        target_value = target_tag

    else:
        assert target_tunnel_type is not None
        normalized = target_tunnel_type.strip().lower()
        matching_links = [
            link
            for link in topology.tunnel_links
            if (
                link.tunnel_type.lower() == normalized
                and link.left in transit_ids
                and link.right in transit_ids
            )
        ]

        if not matching_links:
            available = sorted({
                link.tunnel_type
                for link in topology.tunnel_links
            })
            raise ValueError(
                f"no transit tunnel type {target_tunnel_type!r}; "
                f"available: {available}"
            )

        candidates = []
        for link in matching_links:
            for endpoint in (link.left, link.right):
                if distances[endpoint] == float("inf"):
                    continue
                candidates.append(
                    (
                        distances[endpoint],
                        endpoint,
                        link.tunnel_id,
                        link,
                    )
                )

        if not candidates:
            raise ValueError(
                f"tunnels of type {target_tunnel_type!r} are unreachable "
                f"from elevator {start}"
            )

        _, target, _, selected = min(candidates)
        target_kind = "tunnel_type"
        target_value = selected.tunnel_type
        target_tunnel_id = selected.tunnel_id
        target_tunnel_type_value = selected.tunnel_type
        target_tunnel_length = selected.length

    node_path, route_edges = _reconstruct_route(
        start,
        target,
        previous,
    )

    route = TransitRoute(
        world_id=world_id,
        include_vertical_contacts=include_vertical_contacts,
        start_node=start,
        target_kind=target_kind,
        target_value=target_value,
        target_node=target,
        total_cost=distances[target],
        node_path=node_path,
        edges=route_edges,
        target_tunnel_id=target_tunnel_id,
        target_tunnel_type=target_tunnel_type_value,
        target_tunnel_length=target_tunnel_length,
    )
    return route, lookup
