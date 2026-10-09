"""Prepare a new spatially wider raycast experiment from real cave hits.

This generator does not touch game scripts or original saves. It reuses a
verified saved-world/tile placement and old physical hits as a safe height
reference for NEW XY positions. These positions are not yet measurements.
"""
from __future__ import annotations

from copy import deepcopy
from math import floor, hypot, isfinite
from pathlib import Path

from .ground_density import inspect_ground_density
from .ground_truth import _validated_ground_plan

_ALLOWED_SIZES = (3, 5, 7)
_GRID_FRACTION = 0.31  # Away from BOTH 0.0 and 0.5 voxel sample planes.


def _rotate_local_xy_displacement(
    dx: float, dy: float, rotation: int,
) -> tuple[float, float]:
    """Same quarter-turn convention as tile_to_world()."""
    if rotation == 0:
        return dx, dy
    if rotation == 1:
        return -dy, dx
    if rotation == 2:
        return -dx, -dy
    if rotation == 3:
        return dy, -dx
    raise ValueError("saved tile rotation must be 0..3")


def prepare_expanded_ground_plan(
    original_plan: dict, old_log: str, tile: str | Path,
    *, grid_size: int = 5,
) -> tuple[dict, dict]:
    """Derive a separate 1m-spaced off-grid raycast plan around old hits.

    All source metadata and original file/placement anchors are checked
    by inspect_ground_density. No invented raycast is called 'observed'.
    A nearest genuine game's Z is used ONLY to position the new ray
    window; a miss or non-upward collision remains an unresolved sample.
    """
    if type(grid_size) is not int or grid_size not in _ALLOWED_SIZES:
        raise ValueError("grid_size must be 3, 5 or 7")
    _validated_ground_plan(original_plan)
    profile = inspect_ground_density(original_plan, old_log, tile)
    samples = profile["samples"]
    if len(samples) < 4:
        raise ValueError("need at least four verified game ground hits")
    dims = tuple(int(d) for d in original_plan["tile_dimensions_m"])
    if len(dims) != 3 or any(d < 1 for d in dims):
        raise ValueError("invalid saved tile dimensions")
    rotation = original_plan["layout_rotation_quarter_turns"]
    if type(rotation) is not int or rotation not in (0, 1, 2, 3):
        raise ValueError("invalid saved tile rotation")

    mean_x = sum(float(s["local_xyz"][0]) for s in samples) / len(samples)
    mean_y = sum(float(s["local_xyz"][1]) for s in samples) / len(samples)
    # Every target is 0.31 away from integer lattice planes and 0.19
    # away from half-voxel planes in both X and Y, even after rotation.
    half = grid_size // 2
    grid_x = [floor(mean_x) + i - half + _GRID_FRACTION
              for i in range(grid_size)]
    grid_y = [floor(mean_y) + i - half + _GRID_FRACTION
              for i in range(grid_size)]
    if (grid_x[0] < 1 or grid_y[0] < 1
            or grid_x[-1] > dims[0] - 2
            or grid_y[-1] > dims[1] - 2):
        raise ValueError(
            "expanded grid too close to tile boundary; use --size 3"
        )

    # The prior game hit gives an independently verified world anchor.
    anchor = samples[0]
    ax, ay = (float(v) for v in anchor["local_xyz"][:2])
    awx, awy = (float(v) for v in anchor["world_xy"])
    new_samples = []
    nearest_distances = []
    old_xy = {
        tuple(round(float(v), 5) for v in row["world_xy"])
        for row in samples
    }
    for lane, x in enumerate(grid_x):
        for step, y in enumerate(grid_y):
            world_dx, world_dy = _rotate_local_xy_displacement(
                x - ax, y - ay, rotation
            )
            wx, wy = (round(awx + world_dx, 6),
                      round(awy + world_dy, 6))
            if (not isfinite(wx) or not isfinite(wy)
                    or (round(wx, 5), round(wy, 5)) in old_xy):
                raise ValueError(
                    "new grid overlaps old measurements or has invalid XY; "
                    "cannot treat it as new spatial evidence"
                )
            nearest = min(
                samples,
                key=lambda row: (
                    hypot(x - row["local_xyz"][0],
                          y - row["local_xyz"][1]),
                    row["index"],
                ),
            )
            distance = hypot(
                x - nearest["local_xyz"][0],
                y - nearest["local_xyz"][1],
            )
            nearest_distances.append(distance)
            new_samples.append({
                "world_xy": [wx, wy],
                "estimated_surface_world_z": round(
                    float(nearest["world_hit_z"]), 6
                ),
                "fraction": step / (grid_size - 1),
                "lateral_offset_m": float(lane - half),
                "source_game_hit_index": nearest["index"],
                "distance_from_verified_hit_m": round(distance, 6),
            })

    updated = deepcopy(original_plan)
    updated["critical_edge"] = {
        "world_samples": new_samples,
        "interpretation": (
            "NEW spatial research raycast grid; predicted Z copied from "
            "nearest verified old game hit only to position 3m ray window. "
            "Neither the new floor height nor walkability is known."
        ),
    }
    new_cols = {
        (floor(x), floor(y))
        for x in grid_x for y in grid_y
    }
    shifted_cols = {
        (floor(x - .5), floor(y - .5))
        for x in grid_x for y in grid_y
    }
    updated["experimental_expanded_ground_probe"] = {
        "grid_size": grid_size,
        "spacing_m": 1.0,
        "grid_xy_fraction": _GRID_FRACTION,
        "original_verified_ground_hits": len(samples),
        "new_planned_rays": len(new_samples),
        "distinct_integer_xy_columns": len(new_cols),
        "distinct_half_shift_xy_columns": len(shifted_cols),
        "largest_distance_from_old_verified_hit_m": round(
            max(nearest_distances), 6
        ),
        "requires_new_game_measurements": True,
    }
    _validated_ground_plan(updated)
    return updated, updated["experimental_expanded_ground_probe"]
