from __future__ import annotations

from sm_atlas.underground_navigation import (
    PortalTemplate,
    _canonical_portal_point,
    _contact_faces,
    diagnose_portal_contact_coverage,
    learn_portal_templates,
    match_portal_contacts,
)
from sm_atlas.underground_portals import ObservedPortal
from sm_atlas.underground_topology import (
    LayoutContact,
    LayoutNode,
    LayoutTopology,
)


def node(
    node_id: int,
    *,
    name: str,
    rotation: int,
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
    min_z: float = 0.0,
    max_z: float = 32.0,
) -> LayoutNode:
    return LayoutNode(
        node_id=node_id,
        kind="pocket",
        name=name,
        family="tunnel_pocket",
        tags=("passage",),
        min_x=min_x,
        max_x=max_x,
        min_y=min_y,
        max_y=max_y,
        min_z=min_z,
        max_z=max_z,
        tile_uuid=str(node_id),
        rotation=rotation,
    )


def test_canonical_portal_rotates_back_to_world_face() -> None:
    rotated = node(
        1,
        name="sample_2x3x2.tile",
        rotation=1,
        min_x=0.0,
        max_x=48.0,
        min_y=0.0,
        max_y=32.0,
    )
    template = PortalTemplate(
        tile_name=rotated.name,
        face="x+",
        u=16.0,
        v=16.0,
        observations=3,
        placements=3,
    )

    assert _canonical_portal_point(
        rotated,
        template,
    ) == (32.0, 32.0, 16.0)


def test_contact_faces_are_opposite() -> None:
    left = node(
        1,
        name="a_2x2x2.tile",
        rotation=0,
        min_x=0.0,
        max_x=32.0,
        min_y=0.0,
        max_y=32.0,
    )
    right = node(
        2,
        name="b_2x2x2.tile",
        rotation=0,
        min_x=32.0,
        max_x=64.0,
        min_y=0.0,
        max_y=32.0,
    )
    contact = LayoutContact(
        1,
        2,
        "x",
        32.0,
        32.0,
        1024.0,
    )

    assert _contact_faces(
        contact,
        left,
        right,
    ) == ("x+", "x-")


def test_matching_portals_confirm_face_contact() -> None:
    left = node(
        1,
        name="a_2x2x2.tile",
        rotation=0,
        min_x=0.0,
        max_x=32.0,
        min_y=0.0,
        max_y=32.0,
    )
    right = node(
        2,
        name="b_2x2x2.tile",
        rotation=0,
        min_x=32.0,
        max_x=64.0,
        min_y=0.0,
        max_y=32.0,
    )
    topology = LayoutTopology(
        world_id=23,
        nodes=(left, right),
        contacts=(
            LayoutContact(
                1,
                2,
                "x",
                32.0,
                32.0,
                1024.0,
            ),
        ),
        tunnel_links=(),
        attached_tunnel_endpoints=0,
        unattached_tunnel_endpoints=0,
    )
    templates = [
        PortalTemplate(
            left.name,
            "x+",
            16.0,
            16.0,
            2,
            2,
        ),
        PortalTemplate(
            right.name,
            "x-",
            16.0,
            16.0,
            2,
            2,
        ),
    ]

    matches = match_portal_contacts(
        topology,
        templates,
        match_tolerance=0.1,
    )

    assert len(matches) == 1
    assert matches[0].left == 1
    assert matches[0].right == 2
    assert matches[0].distance == 0.0


def test_template_learning_requires_independent_placements() -> None:
    def portal(node_id: int) -> ObservedPortal:
        return ObservedPortal(
            tunnel_id=node_id,
            side="start",
            node_id=node_id,
            tile_name="tiny_1x1x1.tile",
            family="tunnel_pocket",
            tags=(),
            rotation=0,
            method="ray",
            nearest_face="y-",
            nearest_face_distance=2.0,
            world_face="y-",
            ray_distance=2.0,
            canonical_face="y-",
            canonical_u=8.0,
            canonical_v=8.0,
            endpoint_x=8.0,
            endpoint_y=2.0,
            endpoint_z=8.0,
            portal_x=8.0,
            portal_y=0.0,
            portal_z=8.0,
        )

    templates = learn_portal_templates(
        [portal(1), portal(2)],
        min_placements=2,
    )

    assert len(templates) == 1
    assert templates[0].placements == 2


def test_contact_diagnostics_report_template_gap() -> None:
    left = node(
        1,
        name="a_2x2x2.tile",
        rotation=0,
        min_x=0.0,
        max_x=32.0,
        min_y=0.0,
        max_y=32.0,
    )
    right = node(
        2,
        name="b_2x2x2.tile",
        rotation=0,
        min_x=32.0,
        max_x=64.0,
        min_y=0.0,
        max_y=32.0,
    )
    topology = LayoutTopology(
        world_id=23,
        nodes=(left, right),
        contacts=(
            LayoutContact(
                1,
                2,
                "x",
                32.0,
                32.0,
                1024.0,
            ),
        ),
        tunnel_links=(),
        attached_tunnel_endpoints=0,
        unattached_tunnel_endpoints=0,
    )
    templates = [
        PortalTemplate(
            left.name,
            "y+",
            16.0,
            16.0,
            2,
            2,
        ),
        PortalTemplate(
            right.name,
            "x-",
            16.0,
            16.0,
            2,
            2,
        ),
    ]

    result = diagnose_portal_contact_coverage(
        topology,
        templates,
    )

    assert result["both_tile_templates"] == 1
    assert result["left_face_templates"] == 0
    assert result["right_face_templates"] == 1
    assert result["both_face_templates"] == 0
    assert result["min_distance_buckets"] == {}


def test_contact_diagnostics_measure_opposing_portal_distance() -> None:
    left = node(
        1,
        name="a_2x2x2.tile",
        rotation=0,
        min_x=0.0,
        max_x=32.0,
        min_y=0.0,
        max_y=32.0,
    )
    right = node(
        2,
        name="b_2x2x2.tile",
        rotation=0,
        min_x=32.0,
        max_x=64.0,
        min_y=0.0,
        max_y=32.0,
    )
    topology = LayoutTopology(
        world_id=23,
        nodes=(left, right),
        contacts=(
            LayoutContact(
                1,
                2,
                "x",
                32.0,
                32.0,
                1024.0,
            ),
        ),
        tunnel_links=(),
        attached_tunnel_endpoints=0,
        unattached_tunnel_endpoints=0,
    )
    templates = [
        PortalTemplate(
            left.name,
            "x+",
            8.0,
            16.0,
            2,
            2,
        ),
        PortalTemplate(
            right.name,
            "x-",
            16.0,
            16.0,
            2,
            2,
        ),
    ]

    result = diagnose_portal_contact_coverage(
        topology,
        templates,
    )

    assert result["both_face_templates"] == 1
    assert result["min_distance_buckets"] == {"<=8m": 1}
    assert result["closest_unmatched"][0]["distance"] == 8.0
