from __future__ import annotations

from sm_atlas.underground_features import UndergroundPiece, UndergroundSpawner
from sm_atlas.underground_map import (
    UndergroundRouteOverlay,
    render_underground_map_svg,
)


def test_render_underground_map_svg_includes_features() -> None:
    tunnels = [
        {
            "id": 1,
            "type": "TtVeinRich",
            "length": 10.0,
            "points": [
                (0.0, 0.0, 16.0),
                (10.0, 0.0, 16.0),
            ],
        }
    ]
    caves = [
        UndergroundPiece(
            kind="cave",
            cell_x=0,
            cell_y=0,
            tile_index=2,
            tile_uuid="cave-tile",
            x=0.0,
            y=0.0,
            z=16.0,
            width=64.0,
            depth=64.0,
            height=32.0,
            rotation=0,
            source_x=0,
            source_y=0,
        )
    ]
    pockets = [
        UndergroundPiece(
            kind="pocket",
            cell_x=0,
            cell_y=0,
            tile_index=3,
            tile_uuid="pocket-tile",
            x=16.0,
            y=16.0,
            z=32.0,
            width=16.0,
            depth=32.0,
            height=16.0,
            rotation=1,
            source_x=1,
            source_y=2,
        )
    ]

    spawners = [
        UndergroundSpawner(
            cell_x=0,
            cell_y=0,
            x=20.0,
            y=20.0,
            z=24.0,
            scale_x=48.0,
            scale_y=48.0,
            scale_z=48.0,
            tags=("SPAWN_ENEMY_VOLUME_TRIGGER",),
            trigger_name="Auto",
            react_to_voxel_destruction=True,
        )
    ]

    svg = render_underground_map_svg(
        world_id=23,
        tunnels=tunnels,
        caves=caves,
        pockets=pockets,
        spawners=spawners,
    )

    assert "1 tunnels · 1 caves · 1 pockets · 1 spawners" in svg
    assert 'data-feature="cave"' in svg
    assert 'data-feature="pocket"' in svg
    assert 'data-feature="spawner"' in svg
    assert 'data-tunnel-id="1"' in svg
    assert "Caves (1)" in svg
    assert "Pockets (1)" in svg
    assert "TtVeinRich (1)" in svg


def test_render_underground_map_svg_includes_route_overlay() -> None:
    tunnels = [
        {
            "id": 42,
            "type": "TtVeinRich",
            "length": 41.238,
            "points": [
                (32.0, 0.0, 96.0),
                (56.0, -96.0, 80.0),
            ],
        },
        {
            "id": 269,
            "type": "TtVeinSparkstone",
            "length": 72.323,
            "points": [
                (56.0, -96.0, 80.0),
                (120.0, -120.0, 80.0),
            ],
        },
    ]
    overlay = UndergroundRouteOverlay(
        title="Elevator → TtVeinSparkstone #269 entrance",
        tunnel_ids=(42,),
        contact_segments=(),
        start_point=(32.0, 0.0, 96.0),
        target_point=(56.0, -96.0, 80.0),
        target_tunnel_id=269,
    )

    svg = render_underground_map_svg(
        world_id=23,
        tunnels=tunnels,
        caves=[],
        pockets=[],
        spawners=[],
        route_overlay=overlay,
    )

    assert 'data-feature="route-tunnel"' in svg
    assert 'data-feature="route-target-tunnel"' in svg
    assert 'data-feature="route-start"' in svg
    assert 'data-feature="route-target"' in svg
    assert "Elevator → TtVeinSparkstone #269 entrance" in svg
