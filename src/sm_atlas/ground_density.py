"""Read-only, sample-aligned inspection of underground tile voxel bytes.

This does NOT decode the game's collision mesher. It juxtaposes actual
in-game raycast heights with nearby raw tile columns for format research.
"""
from __future__ import annotations

from collections import defaultdict
from math import ceil, floor, isfinite
from pathlib import Path
from uuid import UUID

from .ground_truth import compare_ground_observations
from .tile_file import probe_tile
from .tile_voxel_space import _dimensions, _load_density_bytes
from .tile_voxel_walk import _surface_sample_height
from .tile_world import world_to_tile
from .underground_topology import LayoutNode


def inspect_ground_density(
    plan: dict, log: str, tile: str | Path, *, z_margin: int = 3,
) -> dict[str, object]:
    """Inspect original bytes near real collision heights; never write files."""
    if type(z_margin) is not int or not 1 <= z_margin <= 8:
        raise ValueError("z_margin must be an integer between 1 and 8")
    comparison = compare_ground_observations(plan, log)
    if not isinstance(plan.get("tile_uuid"), str):
        raise ValueError("plan is missing its anchored tile UUID")
    tile_path = Path(tile).expanduser().resolve()
    if not tile_path.is_file():
        raise ValueError(f"tile file does not exist: {tile_path}")
    dims = _dimensions(tile_path)
    if tuple(plan.get("tile_dimensions_m", ())) != dims:
        raise ValueError("tile dimensions do not match the anchored plan")
    file_uuid = str(UUID(hex=probe_tile(tile_path)["uuid_hex"]))
    if UUID(file_uuid) != UUID(plan["tile_uuid"]):
        raise ValueError("tile UUID differs from anchored saved-world plan")
    bounds = plan.get("world_bounds")
    if not isinstance(bounds, dict):
        raise ValueError("plan has no saved-world bounds")
    lower, upper = bounds.get("min"), bounds.get("max")
    if not (
        isinstance(lower, (list, tuple)) and len(lower) == 3
        and isinstance(upper, (list, tuple)) and len(upper) == 3
        and all(type(v) in (int, float) and isfinite(v) for v in (*lower, *upper))
    ):
        raise ValueError("invalid saved-world bounds")
    rot = plan.get("layout_rotation_quarter_turns")
    if type(rot) is not int or rot not in (0, 1, 2, 3):
        raise ValueError("invalid saved tile rotation")
    node = LayoutNode(
        node_id=int(plan["node_id"]), kind="tile", name="ground profile",
        family="tile", tags=(),
        min_x=lower[0], max_x=upper[0],
        min_y=lower[1], max_y=upper[1],
        min_z=lower[2], max_z=upper[2],
        tile_uuid=file_uuid, rotation=rot,
    )
    expected_bounds = (
        (dims[1], dims[0], dims[2]) if rot & 1 else dims
    )
    if any(abs((upper[i] - lower[i]) - expected_bounds[i]) > 1e-4 for i in range(3)):
        raise ValueError("saved placement bounds do not match rotated tile dimensions")

    volume, unknown_count = _load_density_bytes(tile_path, dims)
    actual = [r for r in comparison["samples"] if r["status"] == "terrain_surface_hit"]
    if not actual:
        raise ValueError("no upward terrain raycast hits in supplied log")

    samples = []
    column_samples: dict[tuple[int, int], list[int]] = defaultdict(list)
    for row in actual:
        wx, wy = row["world_xy"]
        local = world_to_tile(node, dims, (wx, wy, row["actual_z"]))
        if not all(isfinite(v) for v in local):
            raise ValueError("nonfinite local sample coordinate")
        vx, vy = floor(local[0]), floor(local[1])
        if not (0 <= vx < dims[0] and 0 <= vy < dims[1]
                and 0 <= local[2] < dims[2]):
            raise ValueError(f"ground sample {row['index']} outside tile bounds")
        column_samples[(vx, vy)].append(row["index"])
        samples.append({
            "index": row["index"],
            "world_xy": [round(wx, 6), round(wy, 6)],
            "world_hit_z": round(row["actual_z"], 6),
            "local_xyz": [round(v, 6) for v in local],
            "voxel_column_floor_xy": [vx, vy],
        })

    hit_local_z = [r["local_xyz"][2] for r in samples]
    z_lo = max(0, floor(min(hit_local_z)) - z_margin)
    z_hi = min(dims[2] - 1, ceil(max(hit_local_z)) + z_margin)
    columns = []
    for (vx, vy), indices in sorted(column_samples.items()):
        values = []
        for z in range(z_lo, z_hi + 1):
            raw = volume[(vx * dims[1] + vy) * dims[2] + z]
            values.append({
                "z": z,
                "raw_hex": f"{raw:02X}",
                "raw": raw,
                "unknown_or_ff": raw == 255,
                "low4": None if raw == 255 else raw & 0x0F,
                "low5": None if raw == 255 else raw & 0x1F,
            })
        candidates = {}
        for bits in (4, 5):
            crossings = []
            for z in range(max(1, z_lo), min(dims[2] - 1, z_hi) + 1):
                value = _surface_sample_height(
                    (vx, vy, z), volume, dims,
                    density_bits=bits, density_threshold=1 << (bits - 1),
                )
                if value is not None:
                    crossings.append(round(float(value) + lower[2], 6))
            candidates[str(bits)] = crossings
        columns.append({
            "local_xy": [vx, vy],
            "sample_indexes": indices,
            "raw_vertical_bytes": values,
            "candidate_vertical_crossings_world_z": candidates,
        })
    return {
        "world_id": comparison["world_id"],
        "tile_uuid": file_uuid,
        "tile_path": str(tile_path),
        "hits": len(actual),
        "planned_points": comparison["planned_points"],
        "observed_world_z_range": [
            round(min(row["world_hit_z"] for row in samples), 6),
            round(max(row["world_hit_z"] for row in samples), 6),
        ],
        "observed_local_z_range": [
            round(min(hit_local_z), 6), round(max(hit_local_z), 6),
        ],
        "column_z_window": [z_lo, z_hi],
        "unknown_voxels_in_tile": unknown_count,
        "samples": samples,
        "columns": columns,
        "warning": (
            "Nearest integer XY column is diagnostic only: the engine may "
            "interpolate multiple voxel neighbours and use different "
            "bit packing/isosurface coordinates. A crossing is NOT a "
            "validated collision mesh or character-walkability test."
        ),
    }
