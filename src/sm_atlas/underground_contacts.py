"""Independent Python geometry reference for recorded underground contacts.

These are centerline/AABB touches of saved tile-allocation bounds, *not*
validated collisions, entrances, free space, or player-walkable routes.
"""

from __future__ import annotations

from math import isfinite
from typing import Sequence

from .underground_features import UndergroundPiece

Point = tuple[float, float, float]


def segment_touches_piece(
    start: Sequence[float],
    end: Sequence[float],
    piece: UndergroundPiece,
    *,
    spatial: bool = True,
) -> bool:
    """Liang–Barsky/slab segment clipping, inclusive of bounding-box faces."""
    dims = (piece.x, piece.y, piece.z, piece.width, piece.depth, piece.height)
    if (
        len(start) != 3 or len(end) != 3
        or not all(isfinite(v) for v in (*start, *end, *dims))
        or min(piece.width, piece.depth, piece.height) <= 0
    ):
        return False

    lows = (piece.x, piece.y, piece.z)
    highs = (piece.max_x, piece.max_y, piece.max_z)
    enter, leave = 0.0, 1.0
    for axis in range(3 if spatial else 2):
        change = end[axis] - start[axis]
        if change == 0:
            if start[axis] < lows[axis] or start[axis] > highs[axis]:
                return False
            continue
        t0 = (lows[axis] - start[axis]) / change
        t1 = (highs[axis] - start[axis]) / change
        enter = max(enter, min(t0, t1))
        leave = min(leave, max(t0, t1))
        if enter > leave:
            return False
    return True


def classify_tunnel_piece_contacts(
    points: Sequence[Point],
    pieces: Sequence[UndergroundPiece],
) -> tuple[list[int], list[int]]:
    """Return (XYZ touches, XY-projection-only touches) in original order."""
    xyz, xy_only = [], []
    for index, piece in enumerate(pieces):
        projected = False
        for start, end in zip(points, points[1:]):
            if segment_touches_piece(start, end, piece, spatial=False):
                projected = True
                if segment_touches_piece(start, end, piece):
                    xyz.append(index)
                    break
        else:
            if projected:
                xy_only.append(index)
    return xyz, xy_only
