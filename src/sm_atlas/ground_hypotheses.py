"""Read-only tests of fixed 4/5-bit trilinear iso-surface hypotheses.

This is NOT the Scrap Mechanic mesher. Compare a small set of explicit
lattice origins against real raycasts without fitting free parameters.
"""
from __future__ import annotations

from math import ceil, floor, isfinite, sqrt
from pathlib import Path
from statistics import mean, median

from .ground_density import inspect_ground_density
from .tile_voxel_space import _dimensions, _load_density_bytes


def _interpolated_layer(
    volume: bytearray,
    dims: tuple[int, int, int],
    x: float,
    y: float,
    z: int,
    mask: int,
    written: bytearray | None = None,
) -> float | None:
    sx, sy, sz = dims
    if z < 0 or z >= sz or x < 0 or y < 0 or x > sx - 1 or y > sy - 1:
        return None
    x0, y0 = floor(x), floor(y)
    fx, fy = x - x0, y - y0
    density = 0.0
    for xx, wx in ((x0, 1.0 - fx), (x0 + 1, fx)):
        if wx <= 1e-12:
            continue
        for yy, wy in ((y0, 1.0 - fy), (y0 + 1, fy)):
            if wy <= 1e-12:
                continue
            if not 0 <= xx < sx or not 0 <= yy < sy:
                return None
            index = (xx * sy + yy) * sz + z
            raw = volume[index]
            if written is None:
                # Legacy direct callers have no occupancy information.
                if raw == 255:
                    return None
            elif not written[index]:
                return None  # absent record, regardless of byte value
            density += (raw & mask) * wx * wy
    return density


def _candidate_floor_crossings(
    volume: bytearray,
    dims: tuple[int, int, int],
    *,
    local_x: float,
    local_y: float,
    z_min: float,
    z_max: float,
    bits: int,
    sample_shift_x: float,
    sample_shift_y: float,
    sample_shift_z: float,
    written: bytearray | None = None,
) -> list[float]:
    """Find upward-facing iso-crossings in the original game's ray window.

    A crossing is defined by greater-than-threshold packed density below
    and smaller packed density above, using XY bilinear plus Z linear
    interpolation. Return *all* candidate crossings; do not choose the
    one closest to the actual hit.
    """
    if bits not in (4, 5, 6):
        raise ValueError("density bits must be 4, 5 or 6")
    if not (isfinite(z_min) and isfinite(z_max) and z_min < z_max):
        raise ValueError("invalid z-ray interval")
    x = local_x - sample_shift_x
    y = local_y - sample_shift_y
    threshold = 1 << (bits - 1)
    mask = (1 << bits) - 1
    z_start = max(0, floor(z_min - sample_shift_z) - 1)
    z_end = min(dims[2] - 2, ceil(z_max - sample_shift_z))
    hits: list[float] = []
    for z in range(z_start, z_end + 1):
        below = _interpolated_layer(volume, dims, x, y, z, mask, written)
        above = _interpolated_layer(volume, dims, x, y, z + 1, mask, written)
        if (
            below is None or above is None
            or below < threshold or above >= threshold
            or below <= above
        ):
            continue
        crossing = z + sample_shift_z + (
            (below - threshold) / (below - above)
        )
        if z_min - 1e-6 <= crossing <= z_max + 1e-6:
            hits.append(round(crossing, 6))
    return sorted(hits, reverse=True)


def compare_trilinear_hypotheses(
    plan: dict, log: str, tile: str | Path, *,
    include_six_bit: bool = False,
) -> dict[str, object]:
    """Compare 16 legacy or 24 opt-in fixed bit-packing hypotheses.

    Entries with zero/multiple crossings are marked unscored, rather than
    selecting a raycast match after seeing the game's measured height.
    Ranking is diagnostic, not evidence of the real game meshing algorithm.
    """
    profile = inspect_ground_density(plan, log, tile)
    dims = _dimensions(Path(profile["tile_path"]))
    volume, unknown_count, written = _load_density_bytes(
        Path(profile["tile_path"]), dims, return_written=True
    )
    written_ff_count = sum(
        1 for raw, occupied in zip(volume, written)
        if occupied and raw == 255
    )
    min_z = float(plan["world_bounds"]["min"][2])
    rows = profile["samples"]
    candidates = []
    # Six-bit packing is an external, NOT established hypothesis for
    # these older 4096-byte .tile records. Never enable it implicitly.
    for bits in ((4, 5, 6) if include_six_bit else (4, 5)):
        for shift_x in (0.0, 0.5):
            for shift_y in (0.0, 0.5):
                for shift_z in (0.0, 0.5):
                    matching: list[float] = []
                    samples = []
                    for row in rows:
                        index = row["index"]
                        planned_z = float(
                            plan["critical_edge"]["world_samples"][index][
                                "estimated_surface_world_z"
                            ]
                        )
                        lx, ly, _ = row["local_xyz"]
                        roots_local = _candidate_floor_crossings(
                            volume, dims,
                            local_x=lx, local_y=ly,
                            z_min=planned_z - 2.0 - min_z,
                            z_max=planned_z + 1.0 - min_z,
                            bits=bits,
                            sample_shift_x=shift_x,
                            sample_shift_y=shift_y,
                            sample_shift_z=shift_z,
                            written=written,
                        )
                        roots_world = [
                            round(root + min_z, 6) for root in roots_local
                        ]
                        if len(roots_world) == 1:
                            error = roots_world[0] - row["world_hit_z"]
                            matching.append(error)
                            status = "single_candidate"
                        elif not roots_world:
                            status = "no_candidate"
                        else:
                            status = "ambiguous_multiple_candidates"
                        samples.append({
                            "index": index,
                            "observed_world_z": row["world_hit_z"],
                            "candidate_world_z": roots_world,
                            "status": status,
                        })
                    biased_rmse = (
                        sqrt(mean(e * e for e in matching))
                        if matching else None
                    )
                    bias = median(matching) if matching else None
                    residual_rmse = (
                        sqrt(mean((e - bias) ** 2 for e in matching))
                        if matching else None
                    )
                    candidates.append({
                        "bits": bits,
                        "lattice_origin_shift_xyz": [
                            shift_x, shift_y, shift_z,
                        ],
                        "single_candidates": len(matching),
                        "no_candidates": sum(
                            x["status"] == "no_candidate" for x in samples
                        ),
                        "ambiguous_samples": sum(
                            x["status"] == "ambiguous_multiple_candidates"
                            for x in samples
                        ),
                        "median_predicted_minus_observed_m": (
                            round(bias, 6) if bias is not None else None
                        ),
                        "rmse_m": (
                            round(biased_rmse, 6)
                            if biased_rmse is not None else None
                        ),
                        "rmse_after_median_offset_m": (
                            round(residual_rmse, 6)
                            if residual_rmse is not None else None
                        ),
                        "samples": samples,
                    })
    candidates.sort(key=lambda c: (
        -c["single_candidates"],
        c["rmse_m"] if c["rmse_m"] is not None else float("inf"),
        c["bits"],
        c["lattice_origin_shift_xyz"],
    ))
    return {
        "world_id": profile["world_id"],
        "hits_from_game": profile["hits"],
        "models_evaluated": len(candidates),
        "six_bit_hypothesis_opted_in": include_six_bit,
        "unknown_voxels_in_tile": unknown_count,
        "written_ff_voxels_in_tile": written_ff_count,
        "models": candidates,
        "warning": (
            "Exploratory trilinear model, NOT the game collision mesher. "
            "A high match count or small RMSE does not verify the density "
            "bit packing, interpolation scheme or player walkability. "
            "The optional 6-bit model comes from a DIFFERENT, modded runtime "
            "voxel serialization, not confirmed older .tile packing. "
            "Unwritten voxels are now distinguished from literal 0xFF "
            "bytes within recorded tile blocks. This still does not "
            "establish the physical meaning of the FF value. "
            "All 15 measurements come from a small area; no held-out "
            "terrain has been validated."
        ),
    }
