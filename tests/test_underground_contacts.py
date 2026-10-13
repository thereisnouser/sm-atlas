from dataclasses import replace

from sm_atlas.underground_contacts import (
    classify_tunnel_piece_contacts,
    segment_touches_piece,
)
from sm_atlas.underground_features import UndergroundPiece


def piece(x: float = 0, z: float = 0) -> UndergroundPiece:
    return UndergroundPiece(
        kind="cave", cell_x=0, cell_y=0, tile_index=1,
        tile_uuid=None, x=x, y=0, z=z, width=16, depth=16, height=16,
        rotation=0, source_x=0, source_y=0,
    )


def test_segment_box_slabs_respect_saved_xyz_height():
    box = piece()
    assert segment_touches_piece((-10, 8, 8), (24, 8, 8), box)
    assert not segment_touches_piece((-10, 8, 48), (24, 8, 48), box)
    assert segment_touches_piece(
        (-10, 8, 48), (24, 8, 48), box, spatial=False
    )
    assert not segment_touches_piece(
        (-10, -1, 8), (24, -1, 8), box, spatial=False
    )
    assert segment_touches_piece((-4, 8, -8), (8, 8, 8), box)
    assert segment_touches_piece((0, 0, 0), (0, 0, 0), box)
    assert not segment_touches_piece((-1, 0, 0), (-0.1, 0, 0), box)


def test_3d_vs_projection_saved_piece_classification():
    pieces = [
        piece(), piece(16), piece(40, 40), piece(56, 40), piece(75),
    ]
    xyz, projected = classify_tunnel_piece_contacts(
        [(-8, 8, 8), (95, 8, 8)], pieces,
    )
    assert xyz == [0, 1, 4]
    assert projected == [2, 3]


def test_invalid_saved_boxes_cannot_create_contact():
    box = piece()
    assert not segment_touches_piece((0, 0, 0), (2, 2, 2),
                                      replace(box, width=0))
    assert not segment_touches_piece((0, 0, 0), (2, 2, 2),
                                      replace(box, z=float("nan")))
    assert not segment_touches_piece((0, 0, 0), (float("inf"), 2, 2), box)
    assert classify_tunnel_piece_contacts([(0, 0, 0)], [box]) == ([], [])
