"""Compare true game collision normals to experimental raw-density gradients.

Gradient directions do not depend on an arbitrary iso-value threshold.
This isolates one possible reason why a candidate can put the surface at
the wrong height, but does not identify the engine's true collision mesher.
"""
from __future__ import annotations

from math import acos, degrees, floor, hypot, sqrt
from pathlib import Path
from statistics import mean

from .ground_density import inspect_ground_density
from .ground_hypotheses import _interpolated_layer
from .ground_truth import compare_ground_observations
from .tile_voxel_space import _dimensions, _load_density_bytes


DIFFERENCE_STEP_M = 0.01


def _density_xyz(volume: bytearray, dims: tuple[int, int, int],
                 written: bytearray, x: float, y: float,
                 z: float, mask: int) -> float | None:
    """Trilinearly interpolate a recorded field, never invent missing bytes."""
    layer = floor(z)
    dz = z - layer
    bottom = _interpolated_layer(
        volume, dims, x, y, layer, mask, written,
    )
    top = _interpolated_layer(
        volume, dims, x, y, layer + 1, mask, written,
    )
    if bottom is None or top is None:
        return None
    return bottom * (1.0 - dz) + top * dz


def _local_density_gradient(
    volume: bytearray, dims: tuple[int, int, int],
    written: bytearray, point: list[float],
    *, mask: int, shift: tuple[float, float, float],
    step: float = DIFFERENCE_STEP_M,
) -> tuple[float, float, float] | None:
    """Centred finite differences on the candidate scalar field.

    This produces an average derivative at a voxel-grid knot, where a
    piecewise-trilinear field does not have a unique local derivative.
    Such points are separately flagged; they must not be considered
    confirmed physical surface normals.
    """
    p = [float(point[i]) - shift[i] for i in range(3)]
    derivatives = []
    for axis in range(3):
        before = p.copy()
        after = p.copy()
        before[axis] -= step
        after[axis] += step
        a = _density_xyz(volume, dims, written, *before, mask)
        b = _density_xyz(volume, dims, written, *after, mask)
        if a is None or b is None:
            return None
        derivatives.append((b - a) / (2.0 * step))
    return tuple(derivatives)


def _gradient_local_to_world(
    gradient: tuple[float, float, float], rotation: int,
) -> tuple[float, float, float]:
    """Apply the verified saved placement's quarter-turn in the XY plane."""
    gx, gy, gz = gradient
    if rotation == 0:
        return gx, gy, gz
    if rotation == 1:
        return -gy, gx, gz
    if rotation == 2:
        return -gx, -gy, gz
    if rotation == 3:
        return gy, -gx, gz
    raise ValueError("layout_rotation_quarter_turns must be 0..3")


def _normal_at_observed_hit(
    volume: bytearray, dims: tuple[int, int, int],
    written: bytearray, local_point: list[float],
    game_normal: tuple[float, float, float] | list[float],
    *, mask: int, shift: tuple[float, float, float],
    rotation: int,
) -> dict:
    """One observed point, or explicit exclusion when data is unusable."""
    local = tuple(float(local_point[i]) - shift[i] for i in range(3))
    on_knot = any(
        abs(c - round(c)) <= DIFFERENCE_STEP_M * 1.01
        for c in local
    )
    result = {
        "status": "unknown",
        "on_voxel_grid_plane": on_knot,
        "normal_angle_error_degrees": None,
        "model_world_normal": None,
        "model_world_grade_xy": None,
        "game_world_grade_xy": None,
    }
    g = _local_density_gradient(
        volume, dims, written, local_point, mask=mask, shift=shift,
    )
    if g is None:
        result["status"] = "missing_neighbour_or_boundary"
        return result
    gx, gy, gz = _gradient_local_to_world(g, rotation)
    magnitude = sqrt(gx * gx + gy * gy + gz * gz)
    game_magnitude = sqrt(sum(v * v for v in game_normal))
    if magnitude < 1e-8 or game_magnitude < 1e-8:
        result["status"] = "flat_field_or_invalid_normal"
        return result
    if gz >= -1e-7:
        result["status"] = "density_not_falling_upward"
        return result
    if game_normal[2] <= 0.1:
        result["status"] = "game_normal_not_upward"
        return result
    # Decreasing density upward => outward unit normal = -grad / norm.
    predicted = (-gx / magnitude, -gy / magnitude, -gz / magnitude)
    observed = tuple(v / game_magnitude for v in game_normal)
    cosine = max(-1.0, min(
        1.0, sum(a * b for a, b in zip(predicted, observed))
    ))
    result.update({
        "status": "sampled",
        "normal_angle_error_degrees": round(degrees(acos(cosine)), 6),
        "model_world_normal": [round(v, 6) for v in predicted],
        "model_world_grade_xy": [
            round(-gx / gz, 6), round(-gy / gz, 6),
        ],
        "game_world_grade_xy": [
            round(-observed[0] / observed[2], 6),
            round(-observed[1] / observed[2], 6),
        ],
    })
    return result


def audit_ground_field_normals(
    plan: dict, log: str, tile: str | Path, *,
    include_six_bit: bool = False,
) -> dict:
    """Evaluate 4/5-bit, or opt-in 6-bit, fields at actual game hit positions."""
    profile = inspect_ground_density(plan, log, tile)
    observed = compare_ground_observations(plan, log)
    game_by_index = {
        row["index"]: row
        for row in observed["samples"]
        if row["status"] == "terrain_surface_hit"
    }
    rotation = plan.get("layout_rotation_quarter_turns")
    if type(rotation) is not int or rotation not in (0, 1, 2, 3):
        raise ValueError("invalid saved tile rotation")
    dims = _dimensions(Path(profile["tile_path"]))
    volume, missing, written = _load_density_bytes(
        Path(profile["tile_path"]), dims, return_written=True,
    )
    models = []
    bits_set = (4, 5, 6) if include_six_bit else (4, 5)
    for bits in bits_set:
        mask = (1 << bits) - 1
        for sx in (0.0, 0.5):
            for sy in (0.0, 0.5):
                for sz in (0.0, 0.5):
                    shift = (sx, sy, sz)
                    samples = []
                    for row in profile["samples"]:
                        game = game_by_index.get(row["index"])
                        if game is None:
                            raise ValueError(
                                "profile references a missing actual game hit"
                            )
                        diagnostic = _normal_at_observed_hit(
                            volume, dims, written, row["local_xyz"],
                            game["normal_world"], mask=mask, shift=shift,
                            rotation=rotation,
                        )
                        samples.append({
                            "index": row["index"],
                            "lateral_offset_m": game.get("lateral_offset_m"),
                            "fraction": game.get("fraction"),
                            **diagnostic,
                        })
                    valid = [s for s in samples if s["status"] == "sampled"]
                    errs = [s["normal_angle_error_degrees"] for s in valid]
                    models.append({
                        "bits": bits,
                        "lattice_origin_shift_xyz": list(shift),
                        "samples_scored": len(valid),
                        "samples_expected": len(profile["samples"]),
                        "grid_plane_samples_scored": sum(
                            s["on_voxel_grid_plane"] for s in valid
                        ),
                        "density_not_falling_upward": sum(
                            s["status"] == "density_not_falling_upward"
                            for s in samples
                        ),
                        "flat_or_unavailable_samples": sum(
                            s["status"] in (
                                "missing_neighbour_or_boundary",
                                "flat_field_or_invalid_normal",
                            )
                            for s in samples
                        ),
                        "mean_normal_angle_error_degrees": (
                            round(mean(errs), 6) if errs else None
                        ),
                        "max_normal_angle_error_degrees": (
                            round(max(errs), 6) if errs else None
                        ),
                        "samples": samples,
                    })
    models.sort(key=lambda m: (
        -m["samples_scored"],
        m["mean_normal_angle_error_degrees"]
        if m["mean_normal_angle_error_degrees"] is not None
        else float("inf"),
        m["bits"], m["lattice_origin_shift_xyz"],
    ))
    return {
        "world_id": profile["world_id"],
        "measured_hits": len(profile["samples"]),
        "models_evaluated": len(models),
        "six_bit_hypothesis_opted_in": include_six_bit,
        "differentiation_step_m": DIFFERENCE_STEP_M,
        "absent_voxels_in_tile": missing,
        "models_ranked_by_normal_angle": models,
        "warning": (
            "Uses 15 observations in the same tiny game-raycast patch, "
            "not independent validation. These are gradients of an "
            "unverified piecewise-trilinear scalar field at game hit "
            "locations, not the engine's collision triangles. "
            "Changing a scalar cutoff does not change gradient direction "
            "at the same point. Finite differences across voxel-grid "
            "planes average non-smooth derivatives and may be unreliable. "
            "High angular error suggests a mismatch in encoding, "
            "interpolation or coordinate convention, not proof of which. "
            "Missing voxel records and non-falling fields are unscored."
        ),
    }
