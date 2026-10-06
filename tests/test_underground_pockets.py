from __future__ import annotations

from sm_atlas.underground_features import UndergroundPiece
from sm_atlas.underground_layout import _dimensions_from_name
from sm_atlas.underground_pockets import (
    logical_pocket_key,
    reconstruct_logical_pockets,
    source_coverage,
)


def pocket_fragment(
    *,
    x_chunks: int,
    y_chunks: int,
    source_x: int,
    source_y: int,
    source_width: int,
    source_depth: int,
    rotation: int,
) -> UndergroundPiece:
    world_width = source_depth if rotation & 1 else source_width
    world_depth = source_width if rotation & 1 else source_depth

    return UndergroundPiece(
        kind="pocket",
        cell_x=x_chunks // 4,
        cell_y=y_chunks // 4,
        tile_index=78,
        tile_uuid="d380166f-c41f-433d-8a41-70bb7084a201",
        x=x_chunks * 16.0,
        y=y_chunks * 16.0,
        z=48.0,
        width=world_width * 16.0,
        depth=world_depth * 16.0,
        height=48.0,
        rotation=rotation,
        source_x=source_x,
        source_y=source_y,
    )


def test_reconstruct_split_rotated_pocket() -> None:
    # Full tile is 3x3x3 chunks, rotated one quarter-turn.
    # Two save fragments cover source columns [0:2] and [2:3].
    left = pocket_fragment(
        x_chunks=10,
        y_chunks=-5,
        source_x=0,
        source_y=0,
        source_width=2,
        source_depth=3,
        rotation=1,
    )
    right = pocket_fragment(
        x_chunks=10,
        y_chunks=-3,
        source_x=2,
        source_y=0,
        source_width=1,
        source_depth=3,
        rotation=1,
    )

    dimensions = (3, 3, 3)

    assert logical_pocket_key(left, dimensions) == logical_pocket_key(
        right,
        dimensions,
    )
    assert source_coverage([left, right], dimensions) == (True, 0)

    placements = reconstruct_logical_pockets(
        [left, right],
        _dimensions_from_name,
    )

    assert len(placements) == 1
    placement = placements[0]
    assert len(placement.fragments) == 2
    assert placement.source_complete is True
    assert placement.dimensions_match is True
    assert placement.complete is True
    assert placement.expected_width == 48.0
    assert placement.expected_depth == 48.0
    assert placement.expected_height == 48.0
