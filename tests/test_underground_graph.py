from __future__ import annotations

from sm_atlas.underground_features import (
    UndergroundPiece,
    UndergroundSpawner,
)
from sm_atlas.underground_graph import (
    _attach_spawners,
    _cluster_free_endpoints,
    cluster_underground_regions,
)


def piece(
    *,
    kind: str = "pocket",
    x: float,
    y: float,
    z: float,
    width: float = 16.0,
    depth: float = 16.0,
    height: float = 16.0,
) -> UndergroundPiece:
    return UndergroundPiece(
        kind=kind,
        cell_x=0,
        cell_y=0,
        tile_index=1,
        tile_uuid=None,
        x=x,
        y=y,
        z=z,
        width=width,
        depth=depth,
        height=height,
        rotation=0,
        source_x=0,
        source_y=0,
    )


def test_region_clustering_requires_real_3d_overlap() -> None:
    pieces = [
        piece(x=0.0, y=0.0, z=0.0),
        piece(x=8.0, y=8.0, z=8.0),
        piece(x=0.0, y=0.0, z=32.0),
    ]

    regions = cluster_underground_regions(pieces)

    assert len(regions) == 2
    assert sorted(len(region.pieces) for region in regions) == [1, 2]


def test_touching_faces_do_not_merge_regions() -> None:
    pieces = [
        piece(x=0.0, y=0.0, z=0.0),
        piece(x=16.0, y=0.0, z=0.0),
    ]

    regions = cluster_underground_regions(pieces)

    assert len(regions) == 2


def test_free_endpoint_clustering_is_3d() -> None:
    endpoints = [
        (1, "end", (0.0, 0.0, 0.0)),
        (2, "start", (3.0, 4.0, 0.0)),
        (3, "start", (3.0, 4.0, 20.0)),
    ]

    groups = _cluster_free_endpoints(
        endpoints,
        tolerance=6.0,
    )

    assert sorted(len(group) for group in groups) == [1, 2]


def test_spawner_attaches_to_nearby_region() -> None:
    regions = cluster_underground_regions(
        [piece(x=0.0, y=0.0, z=0.0)]
    )
    spawners = [
        UndergroundSpawner(
            cell_x=0,
            cell_y=0,
            x=18.0,
            y=8.0,
            z=8.0,
            scale_x=48.0,
            scale_y=48.0,
            scale_z=48.0,
            tags=("SPAWN_ENEMY_VOLUME_TRIGGER",),
            trigger_name="Auto",
            react_to_voxel_destruction=True,
        )
    ]

    counts, unattached = _attach_spawners(
        spawners,
        regions,
        tolerance=3.0,
    )

    assert counts == {regions[0].region_id: 1}
    assert unattached == 0
