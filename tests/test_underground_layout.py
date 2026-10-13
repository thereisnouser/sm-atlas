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

def test_adjacent_identical_caves_keep_distinct_source_origins() -> None:
    pieces = [
        cave_fragment(
            cell_x=origin + sx, cell_y=sy,
            source_x=sx * 4, source_y=sy * 4,
        )
        for origin in (0, 3)
        for sy in range(2)
        for sx in range(3)
    ]
    groups = reconstruct_logical_structures(list(reversed(pieces)))
    assert len(groups) == 2
    assert [group.min_x for group in groups] == [0.0, 192.0]
    assert all(group.source_aware and group.complete for group in groups)
    assert all(group.source_overlap_cells == 0 for group in groups)


def test_cave_source_origin_handles_all_quarter_rotations() -> None:
    for rotation in range(4):
        pieces = []
        for sy in range(2):
            for sx in range(3):
                if rotation == 0:
                    dx, dy = sx, sy
                elif rotation == 1:
                    dx, dy = 1 - sy, sx
                elif rotation == 2:
                    dx, dy = 2 - sx, 1 - sy
                else:
                    dx, dy = sy, 2 - sx
                original = cave_fragment(
                    cell_x=10 + dx, cell_y=20 + dy,
                    source_x=sx * 4, source_y=sy * 4,
                )
                pieces.append(original.__class__(
                    **{**original.__dict__, "rotation": rotation}
                ))
        groups = reconstruct_logical_structures(pieces)
        assert len(groups) == 1
        assert groups[0].source_aware is True
        assert groups[0].complete is True
        expected = (192.0, 128.0) if rotation % 2 == 0 else (128.0, 192.0)
        assert (groups[0].width, groups[0].depth) == expected


def test_duplicate_source_cells_and_incomplete_caves_are_not_verified() -> None:
    first = cave_fragment(cell_x=0, cell_y=0, source_x=0, source_y=0)
    duplicate = reconstruct_logical_structures([first, first])[0]
    assert duplicate.source_aware is True
    assert duplicate.source_overlap_cells == 1
    assert duplicate.source_complete is False
    assert duplicate.complete is False
    partial = reconstruct_logical_structures([first])[0]
    assert partial.source_complete is False
    assert partial.complete is False
    invalid = cave_fragment(cell_x=0, cell_y=0, source_x=12, source_y=0)
    fallback = reconstruct_logical_structures([invalid])[0]
    assert fallback.source_aware is False
    assert fallback.source_complete is None
