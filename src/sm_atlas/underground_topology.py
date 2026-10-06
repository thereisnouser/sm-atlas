from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from .database import SaveDatabase
from .underground_features import extract_caves, extract_pockets
from .underground_layout import (
    _dimensions_from_name,
    reconstruct_logical_structures,
)
from .underground_pockets import (
    LogicalPocketPlacement,
    reconstruct_logical_pockets,
)
from .underground_tunnels import _load_terrain_table

EPSILON = 1e-6


class LogicalVolume(Protocol):
    @property
    def min_x(self) -> float: ...
    @property
    def max_x(self) -> float: ...
    @property
    def min_y(self) -> float: ...
    @property
    def max_y(self) -> float: ...
    @property
    def min_z(self) -> float: ...
    @property
    def max_z(self) -> float: ...


@dataclass(frozen=True)
class LayoutNode:
    node_id: int
    kind: str
    name: str
    family: str
    tags: tuple[str, ...]
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
    def semantic_role(self) -> str:
        if self.family == "elevator":
            return "elevator"
        if self.family == "cave":
            return "cave"
        if "passage" in self.tags:
            return "passage"
        if self.family == "tunnel_pocket":
            return "tunnel_pocket"
        if self.family == "pocket":
            return "pocket"
        return "other"


@dataclass(frozen=True)
class LayoutContact:
    left: int
    right: int
    axis: str
    overlap_a: float
    overlap_b: float
    area: float


@dataclass(frozen=True)
class LayoutTopology:
    world_id: int
    nodes: tuple[LayoutNode, ...]
    contacts: tuple[LayoutContact, ...]

    def adjacency(self) -> dict[int, set[int]]:
        out = {node.node_id: set() for node in self.nodes}
        for contact in self.contacts:
            out[contact.left].add(contact.right)
            out[contact.right].add(contact.left)
        return out

    def components(self) -> list[list[int]]:
        adjacency = self.adjacency()
        remaining = set(adjacency)
        components: list[list[int]] = []

        while remaining:
            start = min(remaining)
            remaining.remove(start)
            stack = [start]
            component = []

            while stack:
                node_id = stack.pop()
                component.append(node_id)
                for neighbor in adjacency[node_id]:
                    if neighbor not in remaining:
                        continue
                    remaining.remove(neighbor)
                    stack.append(neighbor)

            components.append(sorted(component))

        components.sort(key=lambda item: (-len(item), item[0]))
        return components

    def summary(self, *, top: int = 15) -> dict[str, object]:
        adjacency = self.adjacency()
        components = self.components()
        lookup = {node.node_id: node for node in self.nodes}

        roles = Counter(node.semantic_role for node in self.nodes)
        families = Counter(node.family for node in self.nodes)
        axes = Counter(contact.axis for contact in self.contacts)
        pair_types: Counter[str] = Counter()

        for contact in self.contacts:
            left_role = lookup[contact.left].semantic_role
            right_role = lookup[contact.right].semantic_role
            pair = " <-> ".join(sorted((left_role, right_role)))
            pair_types[pair] += 1

        degree_histogram = Counter(
            len(adjacency[node.node_id])
            for node in self.nodes
        )

        hubs = sorted(
            self.nodes,
            key=lambda node: (
                -len(adjacency[node.node_id]),
                node.node_id,
            ),
        )[:top]

        elevator_nodes = [
            node for node in self.nodes
            if node.semantic_role == "elevator"
        ]
        component_by_node: dict[int, int] = {}
        for index, component in enumerate(components, start=1):
            for node_id in component:
                component_by_node[node_id] = index

        elevator_components = sorted({
            component_by_node[node.node_id]
            for node in elevator_nodes
        })

        return {
            "world_id": self.world_id,
            "nodes": len(self.nodes),
            "contacts": len(self.contacts),
            "families": dict(families.most_common()),
            "roles": dict(roles.most_common()),
            "contact_axes": dict(axes.most_common()),
            "contact_pairs": dict(pair_types.most_common()),
            "components": len(components),
            "largest_component": len(components[0]) if components else 0,
            "isolated_nodes": sum(
                not adjacency[node.node_id]
                for node in self.nodes
            ),
            "degree_histogram": dict(sorted(degree_histogram.items())),
            "elevator_nodes": [node.node_id for node in elevator_nodes],
            "elevator_components": elevator_components,
            "top_hubs": [
                {
                    "id": node.node_id,
                    "role": node.semantic_role,
                    "family": node.family,
                    "name": node.name,
                    "degree": len(adjacency[node.node_id]),
                    "center": tuple(round(v, 3) for v in node.center),
                    "component": component_by_node[node.node_id],
                }
                for node in hubs
            ],
        }


def _positive_overlap(
    left_min: float,
    left_max: float,
    right_min: float,
    right_max: float,
) -> float:
    return min(left_max, right_max) - max(left_min, right_min)


def _face_contact(
    left: LogicalVolume,
    right: LogicalVolume,
) -> tuple[str, float, float] | None:
    x_overlap = _positive_overlap(
        left.min_x, left.max_x, right.min_x, right.max_x
    )
    y_overlap = _positive_overlap(
        left.min_y, left.max_y, right.min_y, right.max_y
    )
    z_overlap = _positive_overlap(
        left.min_z, left.max_z, right.min_z, right.max_z
    )

    x_touch = (
        abs(left.max_x - right.min_x) <= EPSILON
        or abs(right.max_x - left.min_x) <= EPSILON
    )
    y_touch = (
        abs(left.max_y - right.min_y) <= EPSILON
        or abs(right.max_y - left.min_y) <= EPSILON
    )
    z_touch = (
        abs(left.max_z - right.min_z) <= EPSILON
        or abs(right.max_z - left.min_z) <= EPSILON
    )

    if x_touch and y_overlap > EPSILON and z_overlap > EPSILON:
        return "x", y_overlap, z_overlap
    if y_touch and x_overlap > EPSILON and z_overlap > EPSILON:
        return "y", x_overlap, z_overlap
    if z_touch and x_overlap > EPSILON and y_overlap > EPSILON:
        return "z", x_overlap, y_overlap

    return None


def _node_from_pocket(
    node_id: int,
    placement: LogicalPocketPlacement,
) -> LayoutNode:
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
    )


def build_layout_topology(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
) -> LayoutTopology:
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")

    _, value = _load_terrain_table(
        database,
        world_id=world_id,
        limit=limit,
    )

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
            LayoutNode(
                node_id=len(nodes) + 1,
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
            )
        )

    for placement in logical_pockets:
        nodes.append(
            _node_from_pocket(
                len(nodes) + 1,
                placement,
            )
        )

    contacts: list[LayoutContact] = []

    for left_index, left in enumerate(nodes):
        for right in nodes[left_index + 1:]:
            contact = _face_contact(left, right)
            if contact is None:
                continue

            axis, overlap_a, overlap_b = contact
            contacts.append(
                LayoutContact(
                    left=left.node_id,
                    right=right.node_id,
                    axis=axis,
                    overlap_a=overlap_a,
                    overlap_b=overlap_b,
                    area=overlap_a * overlap_b,
                )
            )

    return LayoutTopology(
        world_id=world_id,
        nodes=tuple(nodes),
        contacts=tuple(contacts),
    )
