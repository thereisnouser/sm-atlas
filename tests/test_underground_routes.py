from __future__ import annotations

from sm_atlas.underground_routes import (
    _reconstruct_route,
    _shortest_paths,
    build_transit_edges,
)
from sm_atlas.underground_topology import (
    LayoutContact,
    LayoutNode,
    LayoutTopology,
    LayoutTunnelLink,
)


def node(
    node_id: int,
    *,
    role: str = "tunnel_pocket",
    x: float = 0.0,
    z: float = 0.0,
) -> LayoutNode:
    if role == "elevator":
        family = "elevator"
        tags = ()
    elif role == "cave":
        family = "cave"
        tags = ()
    elif role == "passage":
        family = "pocket"
        tags = ("passage",)
    else:
        family = "tunnel_pocket"
        tags = ()

    return LayoutNode(
        node_id=node_id,
        kind="pocket",
        name=f"node_{node_id}_2x2x2.tile",
        family=family,
        tags=tags,
        min_x=x,
        max_x=x + 32.0,
        min_y=0.0,
        max_y=32.0,
        min_z=z,
        max_z=z + 32.0,
        tile_uuid=str(node_id),
        rotation=0,
    )


def topology() -> LayoutTopology:
    return LayoutTopology(
        world_id=23,
        nodes=(
            node(1, role="elevator", x=0.0),
            node(2, role="passage", x=32.0),
            node(3, x=64.0),
        ),
        contacts=(
            LayoutContact(1, 2, "x", 32.0, 32.0, 1024.0),
            LayoutContact(2, 3, "x", 32.0, 32.0, 1024.0),
        ),
        tunnel_links=(
            LayoutTunnelLink(
                tunnel_id=10,
                tunnel_type="TtVeinRich",
                left=1,
                right=3,
                length=100.0,
            ),
        ),
        attached_tunnel_endpoints=2,
        unattached_tunnel_endpoints=0,
    )


def test_shortest_route_can_prefer_direct_contacts() -> None:
    transit_ids, edges = build_transit_edges(topology())
    distances, previous = _shortest_paths(
        1,
        transit_ids,
        edges,
    )
    nodes, route_edges = _reconstruct_route(
        1,
        3,
        previous,
    )

    assert nodes == (1, 2, 3)
    assert distances[3] == 64.0
    assert [edge.kind for edge in route_edges] == [
        "contact",
        "contact",
    ]


def test_vertical_contacts_are_opt_in() -> None:
    vertical = LayoutTopology(
        world_id=23,
        nodes=(
            node(1, role="elevator", z=0.0),
            node(2, z=32.0),
        ),
        contacts=(
            LayoutContact(1, 2, "z", 32.0, 32.0, 1024.0),
        ),
        tunnel_links=(),
        attached_tunnel_endpoints=0,
        unattached_tunnel_endpoints=0,
    )

    transit_ids, horizontal = build_transit_edges(
        vertical,
        include_vertical_contacts=False,
    )
    _, all_faces = build_transit_edges(
        vertical,
        include_vertical_contacts=True,
    )

    assert transit_ids == {1, 2}
    assert horizontal == []
    assert len(all_faces) == 1
    assert all_faces[0].axis == "z"
