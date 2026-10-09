"""Read-only consistency test for raw density at the *actual* game floor.

This intentionally does not search for iso-surface roots. It checks if a
fixed density threshold could plausibly pass through every measured game
raycast hit when interpolating the recorded bytes in XYZ. Neither a low
scatter nor a close-to-midpoint value validates a collision mesher.
"""
from __future__ import annotations

from math import floor
from pathlib import Path
from statistics import mean, median

from .ground_density import inspect_ground_density
from .ground_hypotheses import _interpolated_layer
from .tile_voxel_space import _dimensions, _load_density_bytes


def _density_at_observed_hit(
    volume: bytearray,
    dims: tuple[int, int, int],
    written: bytearray,
    local_xyz: list[float],
    *,
    mask: int,
    shift_xyz: tuple[float, float, float],
) -> tuple[float, float] | None:
    """Return scalar density and its upward Z derivative at the real hit."""
    x, y, z = (
        float(local_xyz[i]) - shift_xyz[i] for i in range(3)
    )
    z0 = floor(z)
    fraction = z - z0
    below = _interpolated_layer(
        volume, dims, x, y, z0, mask, written
    )
    if below is None:
        return None
    above = _interpolated_layer(
        volume, dims, x, y, z0 + 1, mask, written
    )
    if above is None:
        # At the very top slice, an exact grid-plane hit is evaluable,
        # but its derivative is not. Reject rather than invent a slope.
        return None
    return (
        below * (1 - fraction) + above * fraction,
        above - below,
    )


def audit_observed_isovalues(
    plan: dict, log: str, tile: str | Path, *,
    include_six_bit: bool = False,
) -> dict:
    """Sample candidate scalar fields at measured game hit coordinates.

    Reports the original half-range hypothesis AND the median scalar
    value that would put a constant iso-value through this patch.
    The latter is computed on the SAME samples and is descriptive only.
    """
    profile = inspect_ground_density(plan, log, tile)
    dims = _dimensions(Path(profile["tile_path"]))
    volume, absent, written = _load_density_bytes(
        Path(profile["tile_path"]), dims, return_written=True,
    )
    bits_set = (4, 5, 6) if include_six_bit else (4, 5)
    candidates = []
    for bits in bits_set:
        mask = (1 << bits) - 1
        threshold = 1 << (bits - 1)
        normalized_midpoint = threshold / mask
        for sx in (0.0, 0.5):
            for sy in (0.0, 0.5):
                for sz in (0.0, 0.5):
                    shift = (sx, sy, sz)
                    samples = []
                    for row in profile["samples"]:
                        evaluated = _density_at_observed_hit(
                            volume, dims, written, row["local_xyz"],
                            mask=mask, shift_xyz=shift,
                        )
                        if evaluated is None:
                            samples.append({
                                "index": row["index"], "status": "not_evaluable",
                                "normalized_density": None,
                                "upward_density_change": None,
                            })
                            continue
                        density, vertical_change = evaluated
                        samples.append({
                            "index": row["index"], "status": "sampled",
                            "normalized_density": round(density / mask, 6),
                            "upward_density_change": round(
                                vertical_change / mask, 6
                            ),
                        })
                    valid = [r for r in samples if r["status"] == "sampled"]
                    values = [r["normalized_density"] for r in valid]
                    # Use full precision from rendered sample rows, but
                    # reporting errors to 6 decimals limits precision.
                    fitted = median(values) if values else None
                    falling = sum(
                        r["upward_density_change"] < -1e-9 for r in valid
                    )
                    rising = sum(
                        r["upward_density_change"] > 1e-9 for r in valid
                    )
                    flat = len(valid) - falling - rising
                    candidates.append({
                        "bits": bits,
                        "lattice_origin_shift_xyz": list(shift),
                        "samples_scored": len(valid),
                        "samples_expected": len(profile["samples"]),
                        "falling_density_samples": falling,
                        "rising_density_samples": rising,
                        "flat_density_samples": flat,
                        "fixed_midpoint_normalized": round(normalized_midpoint, 6),
                        "median_observed_normalized_density": (
                            round(fitted, 6) if fitted is not None else None
                        ),
                        "normalized_density_range": (
                            [min(values), max(values)] if values else None
                        ),
                        "mean_abs_distance_from_fixed_midpoint": (
                            round(mean(
                                abs(v - normalized_midpoint) for v in values
                            ), 6) if values else None
                        ),
                        "mean_abs_spread_around_sample_median": (
                            round(mean(abs(v - fitted) for v in values), 6)
                            if values else None
                        ),
                        "samples": samples,
                    })
    # Rank purely for inspection; a flat constant-density volume has
    # zero spread but is *not* an iso-surface and is thus invalid evidence.
    # Coverage first, then density decreasing upward, then fixed-midpoint
    # mismatch; always examine falling/flat counts beside any score.
    candidates.sort(key=lambda row: (
        -row["samples_scored"],
        -row["falling_density_samples"],
        row["mean_abs_distance_from_fixed_midpoint"]
        if row["mean_abs_distance_from_fixed_midpoint"] is not None
        else float("inf"),
        row["bits"], row["lattice_origin_shift_xyz"],
    ))
    return {
        "world_id": profile["world_id"],
        "game_ray_hits": len(profile["samples"]),
        "six_bit_hypothesis_opted_in": include_six_bit,
        "models_evaluated": len(candidates),
        "absent_voxels_in_tile": absent,
        "models": candidates,
        "warning": (
            "Experimental trilinear scalar fields, NOT the game mesher. "
            "All model values are sampled at the SAME observed game hits, "
            "not independent validation. A fitted isovalue is a descriptive "
            "sample median and MUST NOT be used as a corrected decoder. "
            "Flat density can misleadingly give zero spread. "
            "Ground coordinates, horizontal scale, interpolation and actual "
            "collision meshing remain unverified. Missing voxel records "
            "are never replaced with guessed density values."
        ),
    }
