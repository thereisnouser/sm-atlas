from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import sqrt

from .database import SaveDatabase
from .underground_layout import _dimensions_from_name
from .underground_portals import (
    ObservedPortal,
    observe_saved_tunnel_portals,
)
from .underground_topology import (
    EPSILON,
    LayoutContact,
    LayoutNode,
    LayoutTopology,
    build_layout_topology,
)


@dataclass(frozen=True)
class PortalTemplate:
    tile_name: str
    face: str
    u: float
    v: float
    observations: int
    placements: int


@dataclass(frozen=True)
class PortalMatch:
    left: int
    right: int
    left_face: str
    right_face: str
    left_template: PortalTemplate
    right_template: PortalTemplate
    distance: float


@dataclass(frozen=True)
class NavigationCandidateGraph:
    world_id: int
    nodes: tuple[LayoutNode, ...]
    portal_matches: tuple[PortalMatch, ...]
    tunnel_pairs: tuple[tuple[int, int], ...]
    learned_templates: tuple[PortalTemplate, ...]
    face_contacts: int

    def adjacency(self) -> dict[int, set[int]]:
        adjacency = {
            node.node_id: set()
            for node in self.nodes
        }

        for match in self.portal_matches:
            adjacency[match.left].add(match.right)
            adjacency[match.right].add(match.left)

        for left, right in self.tunnel_pairs:
            adjacency[left].add(right)
            adjacency[right].add(left)

        return adjacency

    def components(self) -> list[list[int]]:
        adjacency = self.adjacency()
        remaining = set(adjacency)
        components: list[list[int]] = []

        while remaining:
            start = min(remaining)
            remaining.remove(start)
            stack = [start]
            component: list[int] = []

            while stack:
                node_id = stack.pop()
                component.append(node_id)

                for neighbor in adjacency[node_id]:
                    if neighbor not in remaining:
                        continue
                    remaining.remove(neighbor)
                    stack.append(neighbor)

            components.append(sorted(component))

        components.sort(
            key=lambda component: (
                -len(component),
                component[0],
            )
        )
        return components

    def summary(self, *, top: int = 20) -> dict[str, object]:
        adjacency = self.adjacency()
        components = self.components()
        lookup = {
            node.node_id: node
            for node in self.nodes
        }

        portal_pairs = Counter()
        for match in self.portal_matches:
            roles = sorted(
                (
                    lookup[match.left].semantic_role,
                    lookup[match.right].semantic_role,
                )
            )
            portal_pairs[" <-> ".join(roles)] += 1

        learned_by_tile = Counter(
            template.tile_name
            for template in self.learned_templates
        )

        elevator_nodes = [
            node.node_id
            for node in self.nodes
            if node.semantic_role == "elevator"
        ]

        component_by_node: dict[int, int] = {}
        for index, component in enumerate(components, start=1):
            for node_id in component:
                component_by_node[node_id] = index

        elevator_component_ids = sorted({
            component_by_node[node_id]
            for node_id in elevator_nodes
        })

        elevator_reachable: set[int] = set()
        for component_id in elevator_component_ids:
            elevator_reachable.update(
                components[component_id - 1]
            )

        reachable_roles = Counter(
            lookup[node_id].semantic_role
            for node_id in elevator_reachable
        )

        isolated = [
            node
            for node in self.nodes
            if not adjacency[node.node_id]
        ]

        hubs = sorted(
            self.nodes,
            key=lambda node: (
                -len(adjacency[node.node_id]),
                node.node_id,
            ),
        )[:top]

        tunnel_pair_set = {
            tuple(sorted(pair))
            for pair in self.tunnel_pairs
        }
        portal_pair_set = {
            tuple(sorted((match.left, match.right)))
            for match in self.portal_matches
        }

        return {
            "world_id": self.world_id,
            "nodes": len(self.nodes),
            "face_contacts": self.face_contacts,
            "learned_templates": len(self.learned_templates),
            "learned_tile_types": len(learned_by_tile),
            "portal_matched_contacts": len(portal_pair_set),
            "portal_matches": len(self.portal_matches),
            "portal_pair_roles": dict(
                portal_pairs.most_common()
            ),
            "saved_tunnel_pairs": len(tunnel_pair_set),
            "portal_only_pairs": len(
                portal_pair_set - tunnel_pair_set
            ),
            "tunnel_only_pairs": len(
                tunnel_pair_set - portal_pair_set
            ),
            "both_pair_types": len(
                portal_pair_set & tunnel_pair_set
            ),
            "navigation_pairs": len(
                portal_pair_set | tunnel_pair_set
            ),
            "components": len(components),
            "largest_component": (
                len(components[0])
                if components
                else 0
            ),
            "isolated_nodes": len(isolated),
            "elevator_nodes": elevator_nodes,
            "elevator_components": elevator_component_ids,
            "elevator_reachable_nodes": len(
                elevator_reachable
            ),
            "elevator_reachable_roles": dict(
                reachable_roles.most_common()
            ),
            "isolated": [
                {
                    "id": node.node_id,
                    "role": node.semantic_role,
                    "family": node.family,
                    "tags": list(node.tags),
                    "center": tuple(
                        round(value, 3)
                        for value in node.center
                    ),
                    "name": node.name,
                }
                for node in isolated
            ],
            "top_hubs": [
                {
                    "id": node.node_id,
                    "degree": len(adjacency[node.node_id]),
                    "role": node.semantic_role,
                    "name": node.name,
                    "center": tuple(
                        round(value, 3)
                        for value in node.center
                    ),
                }
                for node in hubs
            ],
        }


def _rounded_key(
    portal: ObservedPortal,
    *,
    step: float,
) -> tuple[str, float, float]:
    return (
        portal.canonical_face,
        round(portal.canonical_u / step) * step,
        round(portal.canonical_v / step) * step,
    )


def learn_portal_templates(
    portals: list[ObservedPortal],
    *,
    min_placements: int = 2,
    cluster_step: float = 4.0,
) -> list[PortalTemplate]:
    if min_placements < 1:
        raise ValueError("min_placements must be at least 1")
    if cluster_step <= 0.0:
        raise ValueError("cluster_step must be positive")

    grouped: dict[
        tuple[str, str, float, float],
        list[ObservedPortal],
    ] = defaultdict(list)

    for portal in portals:
        face, u, v = _rounded_key(
            portal,
            step=cluster_step,
        )
        grouped[
            (
                portal.tile_name,
                face,
                u,
                v,
            )
        ].append(portal)

    templates: list[PortalTemplate] = []

    for (
        tile_name,
        face,
        u,
        v,
    ), observations in grouped.items():
        placements = len({
            portal.node_id
            for portal in observations
        })

        if placements < min_placements:
            continue

        templates.append(
            PortalTemplate(
                tile_name=tile_name,
                face=face,
                u=u,
                v=v,
                observations=len(observations),
                placements=placements,
            )
        )

    templates.sort(
        key=lambda template: (
            template.tile_name,
            template.face,
            template.u,
            template.v,
        )
    )
    return templates


def _canonical_portal_point(
    node: LayoutNode,
    template: PortalTemplate,
) -> tuple[float, float, float] | None:
    dimensions = _dimensions_from_name(node.name)
    if dimensions is None:
        return None

    width = dimensions[0] * 16.0
    depth = dimensions[1] * 16.0
    height = dimensions[2] * 16.0

    if template.face == "x-":
        local = (0.0, template.u, template.v)
    elif template.face == "x+":
        local = (width, template.u, template.v)
    elif template.face == "y-":
        local = (template.u, 0.0, template.v)
    elif template.face == "y+":
        local = (template.u, depth, template.v)
    elif template.face == "z-":
        local = (template.u, template.v, 0.0)
    elif template.face == "z+":
        local = (template.u, template.v, height)
    else:
        return None

    lx, ly, lz = local
    rotation = node.rotation & 3

    if rotation == 1:
        wx = depth - ly
        wy = lx
    elif rotation == 2:
        wx = width - lx
        wy = depth - ly
    elif rotation == 3:
        wx = ly
        wy = width - lx
    else:
        wx = lx
        wy = ly

    return (
        node.min_x + wx,
        node.min_y + wy,
        node.min_z + lz,
    )


def _world_face_for_point(
    node: LayoutNode,
    point: tuple[float, float, float],
) -> str:
    x, y, z = point
    candidates = (
        ("x-", abs(x - node.min_x)),
        ("x+", abs(node.max_x - x)),
        ("y-", abs(y - node.min_y)),
        ("y+", abs(node.max_y - y)),
        ("z-", abs(z - node.min_z)),
        ("z+", abs(node.max_z - z)),
    )

    return min(
        candidates,
        key=lambda item: (
            item[1],
            item[0],
        ),
    )[0]


def _contact_faces(
    contact: LayoutContact,
    left: LayoutNode,
    right: LayoutNode,
) -> tuple[str, str]:
    if contact.axis == "x":
        if abs(left.max_x - right.min_x) <= EPSILON:
            return "x+", "x-"
        return "x-", "x+"

    if contact.axis == "y":
        if abs(left.max_y - right.min_y) <= EPSILON:
            return "y+", "y-"
        return "y-", "y+"

    if contact.axis == "z":
        if abs(left.max_z - right.min_z) <= EPSILON:
            return "z+", "z-"
        return "z-", "z+"

    raise ValueError(
        f"unsupported contact axis: {contact.axis}"
    )


def _point_distance(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    dx = right[0] - left[0]
    dy = right[1] - left[1]
    dz = right[2] - left[2]
    return sqrt(dx * dx + dy * dy + dz * dz)


def match_portal_contacts(
    topology: LayoutTopology,
    templates: list[PortalTemplate],
    *,
    match_tolerance: float = 4.1,
) -> list[PortalMatch]:
    if match_tolerance < 0.0:
        raise ValueError("match_tolerance must be non-negative")

    by_tile: dict[
        str,
        list[PortalTemplate],
    ] = defaultdict(list)

    for template in templates:
        by_tile[template.tile_name].append(template)

    lookup = {
        node.node_id: node
        for node in topology.nodes
    }
    matches: list[PortalMatch] = []

    for contact in topology.contacts:
        left = lookup[contact.left]
        right = lookup[contact.right]
        left_face, right_face = _contact_faces(
            contact,
            left,
            right,
        )

        left_candidates = []
        for template in by_tile.get(left.name, []):
            point = _canonical_portal_point(
                left,
                template,
            )
            if point is None:
                continue
            if _world_face_for_point(left, point) != left_face:
                continue
            left_candidates.append((template, point))

        right_candidates = []
        for template in by_tile.get(right.name, []):
            point = _canonical_portal_point(
                right,
                template,
            )
            if point is None:
                continue
            if _world_face_for_point(right, point) != right_face:
                continue
            right_candidates.append((template, point))

        for left_template, left_point in left_candidates:
            for right_template, right_point in right_candidates:
                distance = _point_distance(
                    left_point,
                    right_point,
                )

                if distance > match_tolerance:
                    continue

                matches.append(
                    PortalMatch(
                        left=left.node_id,
                        right=right.node_id,
                        left_face=left_face,
                        right_face=right_face,
                        left_template=left_template,
                        right_template=right_template,
                        distance=distance,
                    )
                )

    return matches


def build_navigation_candidate_graph(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
    attach_tolerance: float = 4.0,
    min_template_placements: int = 2,
    cluster_step: float = 4.0,
    match_tolerance: float = 4.1,
) -> NavigationCandidateGraph:
    topology = build_layout_topology(
        database,
        world_id=world_id,
        limit=limit,
    )
    _, observed = observe_saved_tunnel_portals(
        database,
        world_id=world_id,
        limit=limit,
        attach_tolerance=attach_tolerance,
    )
    templates = learn_portal_templates(
        observed,
        min_placements=min_template_placements,
        cluster_step=cluster_step,
    )
    matches = match_portal_contacts(
        topology,
        templates,
        match_tolerance=match_tolerance,
    )

    tunnel_pairs = tuple(
        (link.left, link.right)
        for link in topology.tunnel_links
    )

    return NavigationCandidateGraph(
        world_id=world_id,
        nodes=topology.nodes,
        portal_matches=tuple(matches),
        tunnel_pairs=tunnel_pairs,
        learned_templates=tuple(templates),
        face_contacts=len(topology.contacts),
    )
