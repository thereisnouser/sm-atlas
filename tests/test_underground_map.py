from __future__ import annotations

from sm_atlas.underground_features import UndergroundPiece
from sm_atlas.underground_map import render_underground_map_svg


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

    svg = render_underground_map_svg(
        world_id=23,
        tunnels=tunnels,
        caves=caves,
        pockets=pockets,
    )

    assert "1 tunnels · 1 caves · 1 pockets" in svg
    assert 'data-feature="cave"' in svg
    assert 'data-feature="pocket"' in svg
    assert 'data-tunnel-id="1"' in svg
    assert "Caves (1)" in svg
    assert "Pockets (1)" in svg
    assert "TtVeinRich (1)" in svg
