from __future__ import annotations

from sm_atlas.underground_portals import (
    _canonical_face_uv,
    _distance_bucket,
    _nearest_face,
    _ray_exit,
)
from sm_atlas.underground_topology import LayoutNode


def make_node(
    *,
    name: str = "test_2x2x2.tile",
    rotation: int = 0,
    min_x: float = 0.0,
    max_x: float = 32.0,
    min_y: float = 10.0,
    max_y: float = 42.0,
    min_z: float = 20.0,
    max_z: float = 52.0,
) -> LayoutNode:
    return LayoutNode(
        node_id=1,
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
        tile_uuid="uuid",
        rotation=rotation,
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


def test_ray_exit_uses_tunnel_tangent_from_inside_tile() -> None:
    result = _ray_exit(
        (20.0, 26.0, 36.0),
        (1.0, 0.0, 0.0),
        make_node(),
    )

    assert result is not None
    face, distance, point, method = result
    assert face == "x+"
    assert distance == 12.0
    assert point == (32.0, 26.0, 36.0)
    assert method == "ray"


def test_canonical_portal_is_rotation_independent() -> None:
    # Unrotated tile dimensions are 2x3x2 chunks = 32x48x32 m.
    # With rotation=1, a canonical x+ portal at local (32, 16, 16)
    # appears on the world y+ face at (32, 32, 16).
    node = make_node(
        name="sample_2x3x2.tile",
        rotation=1,
        min_x=0.0,
        max_x=48.0,
        min_y=0.0,
        max_y=32.0,
        min_z=0.0,
        max_z=32.0,
    )

    canonical = _canonical_face_uv(
        node,
        (32.0, 32.0, 16.0),
    )

    assert canonical == ("x+", 16.0, 16.0)


def test_distance_bucket_boundaries() -> None:
    assert _distance_bucket(0.5) == "<=0.5m"
    assert _distance_bucket(1.5) == "<=2m"
    assert _distance_bucket(12.0) == "<=16m"
    assert _distance_bucket(20.0) == "<=32m"
    assert _distance_bucket(40.0) == ">32m"
