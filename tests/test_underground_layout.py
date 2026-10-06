from __future__ import annotations

from sm_atlas.underground_features import UndergroundPiece
from sm_atlas.underground_layout import (
    _dimensions_from_name,
    _expected_fragment_count,
    _expected_world_size,
    reconstruct_logical_structures,
)


def cave_fragment(
    *,
    cell_x: int,
    cell_y: int,
    source_x: int,
    source_y: int,
) -> UndergroundPiece:
    return UndergroundPiece(
        kind="cave",
        cell_x=cell_x,
        cell_y=cell_y,
        tile_index=1,
        tile_uuid="52b1c24b-befd-41a6-95c4-54d697737fa6",
        x=cell_x * 64.0,
        y=cell_y * 64.0,
        z=0.0,
        width=64.0,
        depth=64.0,
        height=128.0,
        rotation=0,
        source_x=source_x,
        source_y=source_y,
    )


def test_parse_tile_dimensions_and_expected_cells() -> None:
    dims = _dimensions_from_name("drill2_elevator_12x8x8.tile")

    assert dims == (12, 8, 8)
    assert _expected_fragment_count(dims) == 6
    assert _expected_world_size(dims, 0) == (192.0, 128.0, 128.0)
    assert _expected_world_size(dims, 1) == (128.0, 192.0, 128.0)


def test_reconstruct_elevator_fragments_into_one_structure() -> None:
    fragments = []
    for y in range(2):
        for x in range(3):
            fragments.append(
                cave_fragment(
                    cell_x=10 + x,
                    cell_y=-5 + y,
                    source_x=x * 4,
                    source_y=y * 4,
                )
            )

    structures = reconstruct_logical_structures(fragments)

    assert len(structures) == 1
    structure = structures[0]
    assert structure.family == "elevator"
    assert len(structure.fragments) == 6
    assert structure.expected_fragments == 6
    assert structure.complete is True
    assert structure.width == 192.0
    assert structure.depth == 128.0
    assert structure.height == 128.0
    assert structure.dimensions_match is True
