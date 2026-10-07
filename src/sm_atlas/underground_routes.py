from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from math import sqrt

from .database import SaveDatabase
from .underground_navigation import TRANSIT_ROLES
from .underground_topology import (
    EPSILON,
    LayoutContact,
    LayoutNode,
    LayoutTopology,
    build_layout_topology,
)
from .underground_tunnels import _extract_tunnels, _load_terrain_table


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
class RouteAnchor:
    anchor_id: int
    layout_node_id: int
    point: tuple[float, float, float]
    kind: str
    tunnel_id: int | None = None
    contact_index: int | None = None


@dataclass(frozen=True)
class RouteGraphEdge:
    left: int
    right: int
    kind: str
    weight: float
    layout_node_id: int | None = None
    axis: str | None = None
    tunnel_id: int | None = None
    tunnel_type: str | None = None

    def other(self, anchor_id: int) -> int:
        if anchor_id == self.left:
            return self.right
        if anchor_id == self.right:
            return self.left
        raise ValueError(
            f"anchor {anchor_id} is not part of edge"
        )


@dataclass(frozen=True)
class RouteSegment:
    kind: str
    weight: float
    from_node: int
    to_node: int
    from_point: tuple[float, float, float]
    to_point: tuple[float, float, float]
    layout_node_id: int | None = None
    axis: str | None = None
    tunnel_id: int | None = None
    tunnel_type: str | None = None


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
    target_tunnel_entry_node: int | None = None
    target_tunnel_other_node: int | None = None
    segments: tuple[RouteSegment, ...] = ()
    start_point: tuple[float, float, float] | None = None
    target_point: tuple[float, float, float] | None = None

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
                    "entry_node": self.target_tunnel_entry_node,
                    "other_node": self.target_tunnel_other_node,
                    "full_traverse_cost": round(
                        self.total_cost
                        + (self.target_tunnel_length or 0.0),
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
            "start_point": (
                None
                if self.start_point is None
                else tuple(
                    round(value, 3)
                    for value in self.start_point
                )
            ),
            "target_point": (
                None
                if self.target_point is None
                else tuple(
                    round(value, 3)
                    for value in self.target_point
                )
            ),
            "segments": [
                {
                    "from_node": segment.from_node,
                    "to_node": segment.to_node,
                    "kind": segment.kind,
                    "weight": round(segment.weight, 3),
                    "layout_node_id": segment.layout_node_id,
                    "axis": segment.axis,
                    "tunnel_id": segment.tunnel_id,
                    "tunnel_type": segment.tunnel_type,
                    "from_point": tuple(
                        round(value, 3)
                        for value in segment.from_point
                    ),
                    "to_point": tuple(
                        round(value, 3)
                        for value in segment.to_point
                    ),
                }
                for segment in self.segments
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
                    segment.kind == kind
                    for segment in self.segments
                )
                for kind in ("tunnel", "intra_tile", "contact")
                if any(
                    segment.kind == kind
                    for segment in self.segments
                )
            } if self.segments else {
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
            "cost_breakdown": {
                kind: round(
                    sum(
                        segment.weight
                        for segment in self.segments
                        if segment.kind == kind
                    ),
                    3,
                )
                for kind in ("tunnel", "intra_tile", "contact")
                if any(
                    segment.kind == kind
                    for segment in self.segments
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


def _contact_center(
    contact: LayoutContact,
    left: LayoutNode,
    right: LayoutNode,
) -> tuple[float, float, float]:
    x_min = max(left.min_x, right.min_x)
    x_max = min(left.max_x, right.max_x)
    y_min = max(left.min_y, right.min_y)
    y_max = min(left.max_y, right.max_y)
    z_min = max(left.min_z, right.min_z)
    z_max = min(left.max_z, right.max_z)

    if contact.axis == "x":
        if abs(left.max_x - right.min_x) <= EPSILON:
            x = left.max_x
        else:
            x = left.min_x
        return (
            x,
            (y_min + y_max) / 2.0,
            (z_min + z_max) / 2.0,
        )

    if contact.axis == "y":
        if abs(left.max_y - right.min_y) <= EPSILON:
            y = left.max_y
        else:
            y = left.min_y
        return (
            (x_min + x_max) / 2.0,
            y,
            (z_min + z_max) / 2.0,
        )

    if contact.axis == "z":
        if abs(left.max_z - right.min_z) <= EPSILON:
            z = left.max_z
        else:
            z = left.min_z
        return (
            (x_min + x_max) / 2.0,
            (y_min + y_max) / 2.0,
            z,
        )

    raise ValueError(
        f"unsupported contact axis: {contact.axis}"
    )


def _build_endpoint_route_graph(
    topology: LayoutTopology,
    raw_tunnels: dict[int, dict],
    *,
    include_vertical_contacts: bool,
) -> tuple[
    dict[int, RouteAnchor],
    list[RouteGraphEdge],
    dict[int, int],
    dict[tuple[int, int], int],
]:
    lookup = {
        node.node_id: node
        for node in topology.nodes
    }
    transit_ids = {
        node.node_id
        for node in topology.nodes
        if node.semantic_role in TRANSIT_ROLES
    }

    anchors: dict[int, RouteAnchor] = {}
    anchors_by_node: dict[int, list[int]] = {
        node_id: []
        for node_id in transit_ids
    }
    center_anchor_by_node: dict[int, int] = {}
    tunnel_anchor_by_key: dict[tuple[int, int], int] = {}
    edges: list[RouteGraphEdge] = []
    next_anchor_id = 1

    def add_anchor(
        layout_node_id: int,
        point: tuple[float, float, float],
        kind: str,
        *,
        tunnel_id: int | None = None,
        contact_index: int | None = None,
    ) -> int:
        nonlocal next_anchor_id

        anchor_id = next_anchor_id
        next_anchor_id += 1
        anchors[anchor_id] = RouteAnchor(
            anchor_id=anchor_id,
            layout_node_id=layout_node_id,
            point=(
                float(point[0]),
                float(point[1]),
                float(point[2]),
            ),
            kind=kind,
            tunnel_id=tunnel_id,
            contact_index=contact_index,
        )
        anchors_by_node[layout_node_id].append(anchor_id)
        return anchor_id

    for node_id in sorted(transit_ids):
        center_anchor_by_node[node_id] = add_anchor(
            node_id,
            lookup[node_id].center,
            "center",
        )

    for link in topology.tunnel_links:
        raw = raw_tunnels.get(link.tunnel_id)
        if raw is None or not raw.get("points"):
            continue

        left_anchor = None
        right_anchor = None

        if link.left in transit_ids:
            left_anchor = add_anchor(
                link.left,
                raw["points"][0],
                "tunnel_endpoint",
                tunnel_id=link.tunnel_id,
            )
            tunnel_anchor_by_key[
                (link.tunnel_id, link.left)
            ] = left_anchor

        if link.right in transit_ids:
            right_anchor = add_anchor(
                link.right,
                raw["points"][-1],
                "tunnel_endpoint",
                tunnel_id=link.tunnel_id,
            )
            tunnel_anchor_by_key[
                (link.tunnel_id, link.right)
            ] = right_anchor

        if left_anchor is None or right_anchor is None:
            continue
        if link.left == link.right:
            continue

        edges.append(
            RouteGraphEdge(
                left=left_anchor,
                right=right_anchor,
                kind="tunnel",
                weight=link.length,
                tunnel_id=link.tunnel_id,
                tunnel_type=link.tunnel_type,
            )
        )

    for contact_index, contact in enumerate(
        topology.contacts,
        start=1,
    ):
        if (
            contact.left not in transit_ids
            or contact.right not in transit_ids
        ):
            continue
        if (
            contact.axis == "z"
            and not include_vertical_contacts
        ):
            continue

        point = _contact_center(
            contact,
            lookup[contact.left],
            lookup[contact.right],
        )
        left_anchor = add_anchor(
            contact.left,
            point,
            "contact",
            contact_index=contact_index,
        )
        right_anchor = add_anchor(
            contact.right,
            point,
            "contact",
            contact_index=contact_index,
        )
        edges.append(
            RouteGraphEdge(
                left=left_anchor,
                right=right_anchor,
                kind="contact",
                weight=0.0,
                axis=contact.axis,
            )
        )

    for node_id, node_anchors in anchors_by_node.items():
        for left_index, left_anchor in enumerate(
            node_anchors
        ):
            for right_anchor in node_anchors[
                left_index + 1:
            ]:
                weight = _distance(
                    anchors[left_anchor].point,
                    anchors[right_anchor].point,
                )
                edges.append(
                    RouteGraphEdge(
                        left=left_anchor,
                        right=right_anchor,
                        kind="intra_tile",
                        weight=weight,
                        layout_node_id=node_id,
                    )
                )

    return (
        anchors,
        edges,
        center_anchor_by_node,
        tunnel_anchor_by_key,
    )


def _route_graph_shortest_paths(
    start: int,
    anchors: dict[int, RouteAnchor],
    edges: list[RouteGraphEdge],
) -> tuple[
    dict[int, float],
    dict[int, tuple[int, RouteGraphEdge]],
]:
    adjacency: dict[
        int,
        list[tuple[int, RouteGraphEdge]],
    ] = {
        anchor_id: []
        for anchor_id in anchors
    }

    for edge in edges:
        adjacency[edge.left].append(
            (edge.right, edge)
        )
        adjacency[edge.right].append(
            (edge.left, edge)
        )

    distances = {
        anchor_id: float("inf")
        for anchor_id in anchors
    }
    previous: dict[
        int,
        tuple[int, RouteGraphEdge],
    ] = {}
    distances[start] = 0.0
    queue: list[tuple[float, int]] = [(0.0, start)]

    while queue:
        distance, anchor_id = heappop(queue)
        if distance != distances[anchor_id]:
            continue

        for neighbor, edge in adjacency[anchor_id]:
            candidate = distance + edge.weight
            if candidate >= distances[neighbor]:
                continue

            distances[neighbor] = candidate
            previous[neighbor] = (
                anchor_id,
                edge,
            )
            heappush(
                queue,
                (candidate, neighbor),
            )

    return distances, previous


def _reconstruct_endpoint_route(
    start: int,
    target: int,
    anchors: dict[int, RouteAnchor],
    previous: dict[
        int,
        tuple[int, RouteGraphEdge],
    ],
) -> tuple[
    tuple[int, ...],
    tuple[RouteSegment, ...],
]:
    if start == target:
        return (start,), ()

    anchor_path = [target]
    reversed_edges: list[RouteGraphEdge] = []
    current = target

    while current != start:
        if current not in previous:
            raise ValueError(
                f"target anchor {target} is unreachable "
                f"from {start}"
            )

        parent, edge = previous[current]
        reversed_edges.append(edge)
        anchor_path.append(parent)
        current = parent

    anchor_path.reverse()
    reversed_edges.reverse()

    segments = []
    for index, edge in enumerate(reversed_edges):
        from_anchor = anchors[anchor_path[index]]
        to_anchor = anchors[anchor_path[index + 1]]
        segments.append(
            RouteSegment(
                kind=edge.kind,
                weight=edge.weight,
                from_node=from_anchor.layout_node_id,
                to_node=to_anchor.layout_node_id,
                from_point=from_anchor.point,
                to_point=to_anchor.point,
                layout_node_id=edge.layout_node_id,
                axis=edge.axis,
                tunnel_id=edge.tunnel_id,
                tunnel_type=edge.tunnel_type,
            )
        )

    return tuple(anchor_path), tuple(segments)


def _layout_node_path(
    anchor_path: tuple[int, ...],
    anchors: dict[int, RouteAnchor],
) -> tuple[int, ...]:
    out: list[int] = []

    for anchor_id in anchor_path:
        node_id = anchors[anchor_id].layout_node_id
        if out and out[-1] == node_id:
            continue
        out.append(node_id)

    return tuple(out)


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
    _, terrain = _load_terrain_table(
        database,
        world_id=world_id,
        limit=limit,
    )
    raw_tunnels = {
        int(tunnel["id"]): tunnel
        for tunnel in _extract_tunnels(terrain)
    }

    (
        anchors,
        graph_edges,
        center_anchor_by_node,
        tunnel_anchor_by_key,
    ) = _build_endpoint_route_graph(
        topology,
        raw_tunnels,
        include_vertical_contacts=include_vertical_contacts,
    )

    transit_ids = set(center_anchor_by_node)
    start_node = _elevator_node(
        topology,
        transit_ids,
    )
    start_anchor = center_anchor_by_node[start_node]
    distances, previous = _route_graph_shortest_paths(
        start_anchor,
        anchors,
        graph_edges,
    )

    target_kind: str
    target_value: str
    target_node_id: int
    target_anchor: int
    target_tunnel_id = None
    target_tunnel_type_value = None
    target_tunnel_length = None
    target_tunnel_entry_node = None
    target_tunnel_other_node = None

    if target_node is not None:
        if target_node not in transit_ids:
            raise ValueError(
                f"target node {target_node} is not a transit node"
            )
        target_anchor = center_anchor_by_node[target_node]
        if distances[target_anchor] == float("inf"):
            raise ValueError(
                f"target node {target_node} is unreachable "
                f"from elevator {start_node}"
            )
        target_node_id = target_node
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
            if distances[
                center_anchor_by_node[node_id]
            ] < float("inf")
        ]

        if not candidates:
            available = sorted({
                tag
                for node in topology.nodes
                if node.node_id in transit_ids
                for tag in node.tags
            })
            raise ValueError(
                f"no transit nodes match tag/name "
                f"{target_tag!r}; known tags: {available}"
            )
        if not reachable:
            raise ValueError(
                f"transit nodes matching {target_tag!r} "
                f"are unreachable from elevator {start_node}"
            )

        target_node_id = min(
            reachable,
            key=lambda node_id: (
                distances[
                    center_anchor_by_node[node_id]
                ],
                node_id,
            ),
        )
        target_anchor = center_anchor_by_node[
            target_node_id
        ]
        target_kind = "tag"
        target_value = target_tag

    else:
        assert target_tunnel_type is not None
        normalized = target_tunnel_type.strip().lower()
        matching_links = [
            link
            for link in topology.tunnel_links
            if link.tunnel_type.lower() == normalized
        ]

        if not matching_links:
            available = sorted({
                link.tunnel_type
                for link in topology.tunnel_links
            })
            raise ValueError(
                f"no tunnel type {target_tunnel_type!r}; "
                f"available: {available}"
            )

        candidates = []

        for link in matching_links:
            for node_id in (link.left, link.right):
                anchor_id = tunnel_anchor_by_key.get(
                    (link.tunnel_id, node_id)
                )
                if anchor_id is None:
                    continue
                if distances[anchor_id] == float("inf"):
                    continue

                candidates.append(
                    (
                        distances[anchor_id],
                        link.tunnel_id,
                        node_id,
                        anchor_id,
                        link,
                    )
                )

        if not candidates:
            raise ValueError(
                f"tunnels of type {target_tunnel_type!r} "
                f"are unreachable from elevator {start_node}"
            )

        (
            _,
            _,
            target_node_id,
            target_anchor,
            selected,
        ) = min(candidates)
        target_kind = "tunnel_type"
        target_value = selected.tunnel_type
        target_tunnel_id = selected.tunnel_id
        target_tunnel_type_value = selected.tunnel_type
        target_tunnel_length = selected.length
        target_tunnel_entry_node = target_node_id
        target_tunnel_other_node = (
            selected.right
            if target_node_id == selected.left
            else selected.left
        )

    anchor_path, segments = _reconstruct_endpoint_route(
        start_anchor,
        target_anchor,
        anchors,
        previous,
    )
    node_path = _layout_node_path(
        anchor_path,
        anchors,
    )

    route = TransitRoute(
        world_id=world_id,
        include_vertical_contacts=include_vertical_contacts,
        start_node=start_node,
        target_kind=target_kind,
        target_value=target_value,
        target_node=target_node_id,
        total_cost=distances[target_anchor],
        node_path=node_path,
        edges=(),
        target_tunnel_id=target_tunnel_id,
        target_tunnel_type=target_tunnel_type_value,
        target_tunnel_length=target_tunnel_length,
        target_tunnel_entry_node=target_tunnel_entry_node,
        target_tunnel_other_node=target_tunnel_other_node,
        segments=segments,
        start_point=anchors[start_anchor].point,
        target_point=anchors[target_anchor].point,
    )
    return route, lookup

