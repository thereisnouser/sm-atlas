from __future__ import annotations

from sm_atlas.underground_routes import (
    TransitRoute,
    _add_route_start_anchor,
    _build_endpoint_route_graph,
    _reconstruct_endpoint_route,
    _reconstruct_route,
    _route_graph_evidence_first_paths,
    _route_graph_shortest_paths,
    _select_portal_start,
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


def test_target_tunnel_metadata_reports_entry_and_other_endpoint() -> None:
    lookup = {
        1: node(1, role="elevator", x=0.0),
        2: node(2, role="passage", x=32.0),
    }
    route = TransitRoute(
        world_id=23,
        include_vertical_contacts=False,
        start_node=1,
        target_kind="tunnel_type",
        target_value="TtVeinSparkstone",
        target_node=2,
        total_cost=41.238,
        node_path=(1, 2),
        edges=(),
        target_tunnel_id=269,
        target_tunnel_type="TtVeinSparkstone",
        target_tunnel_length=72.323,
        target_tunnel_entry_node=2,
        target_tunnel_other_node=3,
    )

    result = route.to_dict(lookup)
    tunnel = result["target_tunnel"]

    assert tunnel is not None
    assert tunnel["entry_node"] == 2
    assert tunnel["other_node"] == 3
    assert tunnel["full_traverse_cost"] == 113.561


def test_endpoint_route_graph_charges_intra_tile_travel() -> None:
    elevator = node(
        1,
        role="elevator",
        x=0.0,
    )
    passage = node(
        2,
        role="passage",
        x=32.0,
    )
    room = node(
        3,
        x=64.0,
    )
    graph_topology = LayoutTopology(
        world_id=23,
        nodes=(elevator, passage, room),
        contacts=(),
        tunnel_links=(
            LayoutTunnelLink(
                tunnel_id=10,
                tunnel_type="TtVeinRich",
                left=1,
                right=2,
                length=4.0,
            ),
            LayoutTunnelLink(
                tunnel_id=20,
                tunnel_type="TtVeinSparkstone",
                left=2,
                right=3,
                length=6.0,
            ),
        ),
        attached_tunnel_endpoints=4,
        unattached_tunnel_endpoints=0,
    )
    raw_tunnels = {
        10: {
            "id": 10,
            "type": "TtVeinRich",
            "length": 4.0,
            "points": [
                (30.0, 16.0, 16.0),
                (34.0, 16.0, 16.0),
            ],
        },
        20: {
            "id": 20,
            "type": "TtVeinSparkstone",
            "length": 6.0,
            "points": [
                (60.0, 16.0, 16.0),
                (66.0, 16.0, 16.0),
            ],
        },
    }

    (
        anchors,
        edges,
        center_by_node,
        tunnel_anchor_by_key,
    ) = _build_endpoint_route_graph(
        graph_topology,
        raw_tunnels,
        include_vertical_contacts=False,
    )
    start = center_by_node[1]
    target = tunnel_anchor_by_key[(20, 2)]
    distances, previous = _route_graph_shortest_paths(
        start,
        anchors,
        edges,
    )
    _, segments = _reconstruct_endpoint_route(
        start,
        target,
        anchors,
        previous,
    )

    assert distances[target] == 44.0
    assert [segment.kind for segment in segments] == [
        "intra_tile",
        "tunnel",
        "intra_tile",
    ]
    assert [segment.weight for segment in segments] == [
        14.0,
        4.0,
        26.0,
    ]


def test_evidence_first_routing_prefers_saved_tunnel_over_short_contact() -> None:
    elevator = node(
        1,
        role="elevator",
        x=0.0,
    )
    contact_room = node(
        2,
        role="passage",
        x=32.0,
    )
    tunnel_room = node(
        3,
        role="passage",
        x=64.0,
    )
    graph_topology = LayoutTopology(
        world_id=23,
        nodes=(elevator, contact_room, tunnel_room),
        contacts=(
            LayoutContact(
                1,
                2,
                "x",
                32.0,
                32.0,
                1024.0,
            ),
            LayoutContact(
                2,
                3,
                "x",
                32.0,
                32.0,
                1024.0,
            ),
        ),
        tunnel_links=(
            LayoutTunnelLink(
                tunnel_id=99,
                tunnel_type="TtVeinRich",
                left=1,
                right=3,
                length=100.0,
            ),
        ),
        attached_tunnel_endpoints=2,
        unattached_tunnel_endpoints=0,
    )
    raw_tunnels = {
        99: {
            "id": 99,
            "type": "TtVeinRich",
            "length": 100.0,
            "points": [
                (16.0, 16.0, 16.0),
                (80.0, 16.0, 16.0),
            ],
        },
    }

    (
        anchors,
        edges,
        center_by_node,
        tunnel_anchor_by_key,
    ) = _build_endpoint_route_graph(
        graph_topology,
        raw_tunnels,
        include_vertical_contacts=False,
    )
    start = center_by_node[1]
    target = center_by_node[3]
    scores, previous = _route_graph_evidence_first_paths(
        start,
        anchors,
        edges,
    )
    _, segments = _reconstruct_endpoint_route(
        start,
        target,
        anchors,
        previous,
    )

    assert scores[target][0] == 0
    assert any(
        segment.kind == "tunnel"
        and segment.tunnel_id == 99
        for segment in segments
    )



def test_saved_portal_can_replace_elevator_center_start() -> None:
    elevator = node(
        1,
        role="elevator",
        x=0.0,
    )
    selected = _select_portal_start(
        elevator,
        [
            (5, "a", (80.0, 16.0, 16.0)),
            (67, "b", (10.0, 12.0, 14.0)),
        ],
    )

    assert selected == (67, "b", (10.0, 12.0, 14.0))

    graph_topology = LayoutTopology(
        world_id=23,
        nodes=(elevator,),
        contacts=(),
        tunnel_links=(),
        attached_tunnel_endpoints=0,
        unattached_tunnel_endpoints=0,
    )
    anchors, edges, center_by_node, _ = _build_endpoint_route_graph(
        graph_topology,
        {},
        include_vertical_contacts=False,
    )
    start = _add_route_start_anchor(
        anchors,
        edges,
        layout_node_id=1,
        point=selected[2],
    )

    assert anchors[start].kind == "saved_portal"
    assert anchors[start].point == (10.0, 12.0, 14.0)
    assert any(
        edge.kind == "intra_tile"
        and {edge.left, edge.right}
        == {start, center_by_node[1]}
        for edge in edges
    )
