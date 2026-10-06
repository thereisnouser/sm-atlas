from __future__ import annotations

from sm_atlas.underground_topology import (
    LayoutNode,
    _face_contact,
    _nearest_layout_node,
)


def node(
    node_id: int,
    *,
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
    min_z: float,
    max_z: float,
) -> LayoutNode:
    return LayoutNode(
        node_id=node_id,
        kind="pocket",
        name="test.tile",
        family="pocket",
        tags=(),
        min_x=min_x,
        max_x=max_x,
        min_y=min_y,
        max_y=max_y,
        min_z=min_z,
        max_z=max_z,
    )


def test_face_contact_requires_positive_overlap_on_other_axes() -> None:
    left = node(
        1,
        min_x=0, max_x=16,
        min_y=0, max_y=16,
        min_z=0, max_z=16,
    )
    right = node(
        2,
        min_x=16, max_x=32,
        min_y=4, max_y=12,
        min_z=2, max_z=14,
    )

    assert _face_contact(left, right) == ("x", 8, 12)


def test_corner_touch_is_not_face_contact() -> None:
    left = node(
        1,
        min_x=0, max_x=16,
        min_y=0, max_y=16,
        min_z=0, max_z=16,
    )
    right = node(
        2,
        min_x=16, max_x=32,
        min_y=16, max_y=32,
        min_z=0, max_z=16,
    )

    assert _face_contact(left, right) is None


def test_nearest_layout_node_prefers_smaller_containing_volume() -> None:
    cave = node(
        1,
        min_x=0, max_x=128,
        min_y=0, max_y=128,
        min_z=0, max_z=128,
    )
    pocket = node(
        2,
        min_x=16, max_x=48,
        min_y=16, max_y=48,
        min_z=16, max_z=48,
    )

    match = _nearest_layout_node(
        (32.0, 32.0, 32.0),
        [cave, pocket],
        tolerance=4.0,
    )

    assert match is not None
    assert match.node_id == 2


def test_adjacency_can_ignore_vertical_contacts() -> None:
    from sm_atlas.underground_topology import (
        LayoutContact,
        LayoutTopology,
    )

    nodes = (
        node(
            1,
            min_x=0, max_x=16,
            min_y=0, max_y=16,
            min_z=0, max_z=16,
        ),
        node(
            2,
            min_x=16, max_x=32,
            min_y=0, max_y=16,
            min_z=0, max_z=16,
        ),
        node(
            3,
            min_x=0, max_x=16,
            min_y=0, max_y=16,
            min_z=16, max_z=32,
        ),
    )
    topology = LayoutTopology(
        world_id=23,
        nodes=nodes,
        contacts=(
            LayoutContact(1, 2, "x", 16.0, 16.0, 256.0),
            LayoutContact(1, 3, "z", 16.0, 16.0, 256.0),
        ),
        tunnel_links=(),
        attached_tunnel_endpoints=0,
        unattached_tunnel_endpoints=0,
    )

    adjacency = topology.adjacency(contact_axes={"x", "y"})

    assert adjacency[1] == {2}
    assert adjacency[2] == {1}
    assert adjacency[3] == set()
