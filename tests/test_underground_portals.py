from __future__ import annotations

from sm_atlas.underground_topology import LayoutNode
from sm_atlas.underground_portals import (
    _distance_bucket,
    _nearest_face,
)


def make_node() -> LayoutNode:
    return LayoutNode(
        node_id=1,
        kind="pocket",
        name="test.tile",
        family="tunnel_pocket",
        tags=("passage",),
        min_x=0.0,
        max_x=32.0,
        min_y=10.0,
        max_y=42.0,
        min_z=20.0,
        max_z=52.0,
        tile_uuid="uuid",
        rotation=0,
    )


def test_nearest_face_reports_face_local_coordinates() -> None:
    face, distance, u, v = _nearest_face(
        (1.5, 26.0, 36.0),
        make_node(),
    )

    assert face == "x-"
    assert distance == 1.5
    assert u == 16.0
    assert v == 16.0


def test_distance_bucket_boundaries() -> None:
    assert _distance_bucket(0.5) == "<=0.5m"
    assert _distance_bucket(1.5) == "<=2m"
    assert _distance_bucket(12.0) == "<=16m"
    assert _distance_bucket(20.0) == ">16m"
