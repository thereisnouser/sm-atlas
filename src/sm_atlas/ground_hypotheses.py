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


def _leave_one_track_out_diagnostic(
    models: list[dict],
    planned: list[dict],
) -> dict[str, object]:
    """Select candidates on other tracks, evaluate on the held-out track.

    All hypotheses are fixed before seeing measurements. Only the choice
    between them, and any median vertical bias, may use training hits.
    Missing or ambiguous roots never become a zero-error prediction.
    This test is within one small site, NOT new-terrain generalization.
    """
    offsets = []
    for row in planned:
        if not isinstance(row, dict):
            return {"status": "unavailable_track_metadata", "folds": []}
        offset = row.get("lateral_offset_m")
        if type(offset) not in (int, float) or not isfinite(offset):
            return {"status": "unavailable_track_metadata", "folds": []}
        offsets.append(float(offset))
    tracks = sorted(set(offsets))
    if len(tracks) < 3:
        return {
            "status": "insufficient_distinct_tracks",
            "distinct_tracks": len(tracks),
            "folds": [],
        }

    for model in models:
        samples = model.get("samples")
        if not isinstance(samples, list) or len(samples) != len(planned):
            raise ValueError("model sample count differs from the measured plan")
        if any(row.get("index") != i for i, row in enumerate(samples)):
            raise ValueError("model sample indices are not plan-aligned")

    def residual(row: dict) -> float | None:
        if row["status"] != "single_candidate":
            return None
        candidates = row["candidate_world_z"]
        if len(candidates) != 1:
            raise ValueError("a scored sample must have exactly one crossing")
        predicted = candidates[0]
        observed = row["observed_world_z"]
        if not isfinite(predicted) or not isfinite(observed):
            raise ValueError("nonfinite predicted or observed ground height")
        return float(predicted - observed)

    folds = []
    for held_out in tracks:
        held = [i for i, lane in enumerate(offsets) if lane == held_out]
        train = [i for i, lane in enumerate(offsets) if lane != held_out]
        scored = []
        for model in models:
            errors = [e for i in train
                      if (e := residual(model["samples"][i])) is not None]
            if not errors:
                continue
            train_rmse = sqrt(mean(e * e for e in errors))
            scored.append((
                -len(errors), train_rmse, model["bits"],
                tuple(model["lattice_origin_shift_xyz"]),
                model, errors,
            ))
        if not scored:
            folds.append({
                "held_out_lateral_offset_m": held_out,
                "status": "no_scorable_training_candidate",
                "training_samples": len(train),
                "held_out_samples": len(held),
            })
            continue
        _, train_rmse, _, _, chosen, train_errors = min(
            scored, key=lambda entry: entry[:4]
        )
        bias_from_train = median(train_errors)
        holdout_errors = [
            e for i in held
            if (e := residual(chosen["samples"][i])) is not None
        ]
        folds.append({
            "held_out_lateral_offset_m": held_out,
            "status": (
                "scored" if holdout_errors else "no_unambiguous_held_out_roots"
            ),
            "chosen_bits": chosen["bits"],
            "chosen_lattice_origin_shift_xyz": chosen["lattice_origin_shift_xyz"],
            "training_samples": len(train),
            "training_unambiguous": len(train_errors),
            "training_rmse_m": round(train_rmse, 6),
            "training_median_bias_m": round(bias_from_train, 6),
            "held_out_samples": len(held),
            "held_out_unambiguous": len(holdout_errors),
            "held_out_missing_or_ambiguous": len(held) - len(holdout_errors),
            "held_out_rmse_m": (
                round(sqrt(mean(e * e for e in holdout_errors)), 6)
                if holdout_errors else None
            ),
            "held_out_rmse_after_training_bias_m": (
                round(sqrt(mean(
                    (e - bias_from_train) ** 2 for e in holdout_errors
                )), 6) if holdout_errors else None
            ),
        })
    return {
        "status": (
            "within_site_diagnostic_only"
            if all(f["status"] == "scored" for f in folds)
            else "incomplete_within_site_diagnostic"
        ),
        "distinct_tracks": len(tracks),
        "folds": folds,
        "warning": (
            "Each lane is held out during model choice and bias fitting, "
            "but all lanes sample one small nearby patch. This is NOT an "
            "independent validation tile, terrain surface or traversable "
            "route. Coverage and failures remain explicit."
        ),
    }


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
                    ff_sensitive_samples = 0
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
                        # Compare to the former FF-as-unknown behaviour.
                        # This never influences model selection or roots.
                        former_roots = _candidate_floor_crossings(
                            volume, dims,
                            local_x=lx, local_y=ly,
                            z_min=planned_z - 2.0 - min_z,
                            z_max=planned_z + 1.0 - min_z,
                            bits=bits,
                            sample_shift_x=shift_x,
                            sample_shift_y=shift_y,
                            sample_shift_z=shift_z,
                        )
                        if former_roots != roots_local:
                            ff_sensitive_samples += 1
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
                        "ff_sensitive_samples": ff_sensitive_samples,
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
    cross_track = _leave_one_track_out_diagnostic(
        candidates, plan["critical_edge"]["world_samples"]
    )
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
        "cross_track_holdout": cross_track,
        "warning": (
            "Exploratory trilinear model, NOT the game collision mesher. "
            "A high match count or small RMSE does not verify the density "
            "bit packing, interpolation scheme or player walkability. "
            "The optional 6-bit model comes from a DIFFERENT, modded runtime "
            "voxel serialization, not confirmed older .tile packing. "
            "Unwritten voxels are now distinguished from literal 0xFF "
            "bytes within recorded tile blocks. ff_sensitive_samples "
            "counts differences in candidate crossings against the "
            "former FF-as-unknown behaviour, not verified corrections. "
            "This does not establish the physical meaning of FF. "
            "The cross_track_holdout report selects a model and vertical "
            "offset on the other two tracks and tests the withheld third "
            "without using its heights for selection. All tracks are still "
            "from one tiny patch; no independent terrain has been validated."
        ),
    }
