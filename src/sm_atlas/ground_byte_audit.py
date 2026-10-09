"""Read-only byte forensics aligned with *measured* in-game cave ground.

This reports raw voxel-byte transitions near true raycast heights. No model
is trained, no implicit voxel packing is chosen, and no game/save is edited.
"""
from __future__ import annotations

from collections import Counter
from math import floor
from pathlib import Path

from .ground_density import inspect_ground_density
from .tile_voxel_space import _dimensions, _load_density_bytes


def _nearby_columns(samples: list[dict], dims: tuple[int, int, int],
                    radius: int) -> list[dict]:
    """Assign each sampled XY voxel column to the nearest real raycast.

    Multiple rays may fall into a single integer XY column. They MUST NOT
    be counted as independent voxel observations. The nearest real hit
    defines the reference Z for each *unique* inspected column.
    """
    sx, sy, _ = dims
    assigned: dict[tuple[int, int], tuple[tuple[float, int], dict]] = {}
    for sample in samples:
        x, y, _ = sample["local_xyz"]
        for vx in range(floor(x) - radius, floor(x) + radius + 1):
            if not 0 <= vx < sx:
                continue
            for vy in range(floor(y) - radius, floor(y) + radius + 1):
                if not 0 <= vy < sy:
                    continue
                distance2 = (vx + 0.5 - x) ** 2 + (vy + 0.5 - y) ** 2
                candidate = (distance2, sample["index"])
                key = (vx, vy)
                if key not in assigned or candidate < assigned[key][0]:
                    assigned[key] = (candidate, sample)
    return [
        {
            "local_xy": [x, y],
            "reference_hit_index": row["index"],
            "reference_hit_local_z": row["local_xyz"][2],
            "distance_to_reference_xy_m": round(dist2 ** 0.5, 6),
        }
        for (x, y), ((dist2, _), row) in sorted(assigned.items())
    ]


def _summarize_pairs(pairs: list[dict], *, shift: float) -> dict:
    complete = [p for p in pairs if p["status"] == "recorded_pair"]
    transitions = []
    for bit in range(8):
        below = sum(bool(p["raw_below"] & (1 << bit)) for p in complete)
        above = sum(bool(p["raw_above"] & (1 << bit)) for p in complete)
        lost = sum(bool(p["raw_below"] & (1 << bit))
                   and not (p["raw_above"] & (1 << bit))
                   for p in complete)
        gained = sum(not (p["raw_below"] & (1 << bit))
                     and bool(p["raw_above"] & (1 << bit))
                     for p in complete)
        transitions.append({
            "bit": bit,
            "below_set": below,
            "above_set": above,
            "set_to_clear": lost,
            "clear_to_set": gained,
            "unchanged": len(complete) - lost - gained,
        })

    mask_checks = []
    for bits in (4, 5, 6):
        mask = (1 << bits) - 1
        threshold = 1 << (bits - 1)
        drops = rises = both_high = both_low = 0
        for pair in complete:
            low = pair["raw_below"] & mask
            high = pair["raw_above"] & mask
            if low >= threshold and high < threshold:
                drops += 1
            elif low < threshold and high >= threshold:
                rises += 1
            elif low >= threshold and high >= threshold:
                both_high += 1
            else:
                both_low += 1
        mask_checks.append({
            "bits": bits,
            "threshold": threshold,
            "solid_below_air_above": drops,
            "air_below_solid_above": rises,
            "both_above_threshold": both_high,
            "both_below_threshold": both_low,
        })

    counts = Counter(
        (pair["raw_below"], pair["raw_above"]) for pair in complete
    )
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:12]
    return {
        "sample_origin_shift_z": shift,
        "candidate_columns": len(pairs),
        "recorded_pairs": len(complete),
        "missing_or_out_of_bounds_pairs": len(pairs) - len(complete),
        "bit_transitions": transitions,
        "masked_midpoint_checks": mask_checks,
        "common_raw_pairs": [
            {"below_hex": f"{low:02X}", "above_hex": f"{high:02X}",
             "count": count}
            for (low, high), count in top
        ],
        "pairs": pairs,
    }


def audit_ground_voxel_bytes(
    plan: dict, log: str, tile, *, radius_voxels: int = 1,
) -> dict:
    """Inspect byte *evidence*, not a candidate game collision surface.

    Compare neighbouring encoded voxel values on either side of actual
    raycast Z for the two established sample-origin hypotheses (0, 0.5).
    Voxel columns are deduplicated. Nearest-ray Z for nearby columns is
    an approximation, not an extra game measurement.
    """
    if type(radius_voxels) is not int or not 0 <= radius_voxels <= 3:
        raise ValueError("radius_voxels must be an integer from 0 to 3")
    profile = inspect_ground_density(plan, log, tile)
    tile_path = Path(profile["tile_path"])
    dims = _dimensions(tile_path)
    volume, absent, written = _load_density_bytes(
        tile_path, dims, return_written=True,
    )
    columns = _nearby_columns(profile["samples"], dims, radius_voxels)
    sz = dims[2]
    shifts = []
    for shift in (0.0, 0.5):
        pairs = []
        for column in columns:
            x, y = column["local_xy"]
            z = floor(column["reference_hit_local_z"] - shift)
            pair = {
                **column,
                "sample_z_indices": [z, z + 1],
                "status": "out_of_bounds",
                "raw_below": None,
                "raw_above": None,
            }
            if 0 <= z < sz - 1:
                below_index = (x * dims[1] + y) * sz + z
                above_index = below_index + 1
                if written[below_index] and written[above_index]:
                    pair.update({
                        "status": "recorded_pair",
                        "raw_below": int(volume[below_index]),
                        "raw_above": int(volume[above_index]),
                    })
                else:
                    pair["status"] = "unwritten_voxel"
            pairs.append(pair)
        shifts.append(_summarize_pairs(pairs, shift=shift))
    return {
        "world_id": profile["world_id"],
        "tile_uuid": profile["tile_uuid"],
        "tile_dimensions_m": list(dims),
        "game_ray_hits": len(profile["samples"]),
        "unique_voxel_columns": len(columns),
        "radius_voxels": radius_voxels,
        "absent_voxels_in_tile": absent,
        "written_ff_voxels_in_tile": sum(
            raw == 255 and bool(present)
            for raw, present in zip(volume, written)
        ),
        "shifts": shifts,
        "warning": (
            "Read-only byte statistics near measured game floor, not the "
            "engine's verified voxel density encoding or collision mesh. "
            "A nearby column borrows height from the closest actual hit; "
            "its height is NOT another measured game point. Each column "
            "is counted once, not once per nearby ray. Midpoint tests "
            "assume unverified density bits, thresholds and sample origins. "
            "Missing voxel records are excluded, not assigned a density."
        ),
    }
