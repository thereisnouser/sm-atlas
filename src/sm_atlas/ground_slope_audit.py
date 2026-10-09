"""Read-only slope audit of measured terrain against voxel hypotheses.

Raycast point heights and normals provide independent local surface
orientation observations. Neither can establish player capsule clearance.
"""
from __future__ import annotations

from math import hypot
from statistics import mean

from .ground_hypotheses import compare_trilinear_hypotheses
from .ground_truth import compare_ground_observations


def _lane_rows(samples: list[dict]) -> list[tuple[float, list[dict]]]:
    lanes: dict[float, list[dict]] = {}
    for sample in samples:
        lateral = sample["lateral_offset_m"]
        if lateral is None:
            raise ValueError("plan samples lack lateral_offset_m")
        lanes.setdefault(float(lateral), []).append(sample)
    return [
        (offset, sorted(rows, key=lambda row: row["fraction"]))
        for offset, rows in sorted(lanes.items())
    ]


def _directional_grade_check(a: dict, b: dict) -> dict | None:
    """Use real consecutive game hits; never bridge a missing measurement."""
    if (a["status"] != "terrain_surface_hit"
            or b["status"] != "terrain_surface_hit"):
        return None
    dx = b["world_xy"][0] - a["world_xy"][0]
    dy = b["world_xy"][1] - a["world_xy"][1]
    span = hypot(dx, dy)
    if span <= 1e-9:
        return None
    ux, uy = dx / span, dy / span
    actual_grade = (b["actual_z"] - a["actual_z"]) / span
    estimates = [
        -(r["normal_world"][0] * ux + r["normal_world"][1] * uy)
        / r["normal_world"][2]
        for r in (a, b)
        if abs(r["normal_world"][2]) > 0.1
    ]
    if not estimates:
        return None
    normal_grade = mean(estimates)
    return {
        "from_index": a["index"],
        "to_index": b["index"],
        "horizontal_span_m": round(span, 6),
        "observed_directional_grade": round(actual_grade, 6),
        "normal_implied_directional_grade": round(normal_grade, 6),
        "absolute_disagreement": round(
            abs(actual_grade - normal_grade), 6
        ),
    }


def _cross_track_checks(lanes: list[tuple[float, list[dict]]]) -> list[dict]:
    """Measure cross-track slopes at matching fractions in adjacent lanes.

    A cross-track pair must contain two actual hits. Intermediate lanes
    are not skipped, even if all their raycasts missed.
    """
    checks = []
    for (left_offset, left), (right_offset, right) in zip(lanes, lanes[1:]):
        by_fraction = {row["fraction"]: row for row in right}
        for a in left:
            b = by_fraction.get(a["fraction"])
            if b is None:
                continue
            check = _directional_grade_check(a, b)
            if check is not None:
                checks.append({
                    **check,
                    "fraction": a["fraction"],
                    "from_lateral_offset_m": left_offset,
                    "to_lateral_offset_m": right_offset,
                })
    return checks


def _score_model_segment(segment: dict, rows: dict[int, dict]) -> dict | None:
    """Compare a candidate root pair to the exact observed game-hit pair."""
    a = rows.get(segment["from_index"])
    b = rows.get(segment["to_index"])
    if (a is None or b is None
            or a["status"] != "single_candidate"
            or b["status"] != "single_candidate"):
        return None
    span = segment["horizontal_span_m"]
    if span <= 0:
        return None
    model_grade = (b["candidate_world_z"][0] - a["candidate_world_z"][0]) / span
    actual_grade = segment["observed_directional_grade"]
    normal_grade = segment["normal_implied_directional_grade"]
    return {
        "from_index": segment["from_index"],
        "to_index": segment["to_index"],
        "horizontal_span_m": span,
        "observed_directional_grade": actual_grade,
        "normal_implied_directional_grade": normal_grade,
        "model_directional_grade": round(model_grade, 6),
        "absolute_grade_error": round(abs(model_grade - actual_grade), 6),
        "absolute_normal_grade_error": round(
            abs(model_grade - normal_grade), 6
        ),
    }


def _direction_bias_diagnostic(scored_segments: list[dict]) -> dict:
    """Describe signed slope mismatch; NEVER correct a model using this fit.

    A constant plane tilt gives almost identical signed errors on every
    adjacent segment. A wavy model can have zero mean bias but large
    residual errors. These are in-sample descriptions, not validation.
    """
    if not scored_segments:
        return {
            "observed_mean_grade": None,
            "model_mean_grade": None,
            "mean_signed_grade_error": None,
            "mae_after_constant_tilt_diagnostic": None,
        }
    errors = [
        segment["model_directional_grade"]
        - segment["observed_directional_grade"]
        for segment in scored_segments
    ]
    average_error = mean(errors)
    return {
        "observed_mean_grade": round(
            mean(segment["observed_directional_grade"]
                 for segment in scored_segments), 6
        ),
        "model_mean_grade": round(
            mean(segment["model_directional_grade"]
                 for segment in scored_segments), 6
        ),
        "mean_signed_grade_error": round(average_error, 6),
        "mae_after_constant_tilt_diagnostic": round(
            mean(abs(error - average_error) for error in errors), 6
        ),
    }


def audit_ground_slopes(
    plan: dict, log: str, tile, *, include_six_bit: bool = False,
) -> dict:
    """Compare observed grades to normals and modelled end-to-end rises.

    Scores only end-to-end lane rises with two actual upward hits and
    unambiguous single model roots at both endpoints. Does not promote
    a model based on artificially small height residuals.
    """
    observed = compare_ground_observations(plan, log)
    # Preserve existing 16-hypothesis behaviour unless explicitly opted in.
    if include_six_bit:
        hypotheses = compare_trilinear_hypotheses(
            plan, log, tile, include_six_bit=True
        )
    else:
        hypotheses = compare_trilinear_hypotheses(plan, log, tile)

    measured_lanes = _lane_rows(observed["samples"])
    cross_track_checks = _cross_track_checks(measured_lanes)
    lane_summary = []
    for lateral, lane in measured_lanes:
        valid = [r for r in lane if r["status"] == "terrain_surface_hit"]
        # Avoid bridging a missing observation to infer local normals.
        normal_checks = []
        for a, b in zip(lane, lane[1:]):
            check = _directional_grade_check(a, b)
            if check is not None:
                normal_checks.append(check)
        end_rise = None
        end_span = None
        if (len(lane) >= 2
                and lane[0]["status"] == "terrain_surface_hit"
                and lane[-1]["status"] == "terrain_surface_hit"):
            end_rise = lane[-1]["actual_z"] - lane[0]["actual_z"]
            end_span = hypot(
                lane[-1]["world_xy"][0] - lane[0]["world_xy"][0],
                lane[-1]["world_xy"][1] - lane[0]["world_xy"][1],
            )
        lane_summary.append({
            "lateral_offset_m": lateral,
            "start_index": lane[0]["index"],
            "end_index": lane[-1]["index"],
            "measured_hits": len(valid),
            "expected_hits": len(lane),
            "end_to_end_span_m": (
                round(end_span, 6) if end_span is not None else None
            ),
            "observed_end_to_end_rise_m": (
                round(end_rise, 6) if end_rise is not None else None
            ),
            "adjacent_normal_checks": normal_checks,
            "mean_normal_grade_disagreement": (
                round(mean(v["absolute_disagreement"] for v in normal_checks), 6)
                if normal_checks else None
            ),
        })

    models = []
    for candidate in hypotheses["models"]:
        rows = {r["index"]: r for r in candidate["samples"]}
        lane_scores = []
        for lane in lane_summary:
            rise = lane["observed_end_to_end_rise_m"]
            if rise is None:
                continue
            left = rows.get(lane["start_index"])
            right = rows.get(lane["end_index"])
            if (left is None or right is None
                    or left["status"] != "single_candidate"
                    or right["status"] != "single_candidate"):
                continue
            model_rise = (
                right["candidate_world_z"][0]
                - left["candidate_world_z"][0]
            )
            lane_scores.append({
                "lateral_offset_m": lane["lateral_offset_m"],
                "observed_rise_m": rise,
                "model_rise_m": round(model_rise, 6),
                "rise_error_m": round(model_rise - rise, 6),
            })
        # Adjacent-segment grades expose local shape mismatch that a
        # matching end-to-end lane rise would conceal. Do not bridge
        # gaps: the validated raycast comparison supplies normal checks
        # only for consecutive pairs of actual upward ground hits.
        local_grade_scores = []
        for lane in lane_summary:
            for segment in lane["adjacent_normal_checks"]:
                scored = _score_model_segment(segment, rows)
                if scored is not None:
                    local_grade_scores.append({
                        **scored,
                        "lateral_offset_m": lane["lateral_offset_m"],
                    })
        cross_grade_scores = []
        for segment in cross_track_checks:
            scored = _score_model_segment(segment, rows)
            if scored is not None:
                cross_grade_scores.append({
                    **scored,
                    "fraction": segment["fraction"],
                    "from_lateral_offset_m": segment["from_lateral_offset_m"],
                    "to_lateral_offset_m": segment["to_lateral_offset_m"],
                })
        patch_grade_scores = local_grade_scores + cross_grade_scores
        models.append({
            "bits": candidate["bits"],
            "lattice_origin_shift_xyz": candidate["lattice_origin_shift_xyz"],
            "single_candidates": candidate["single_candidates"],
            "ff_sensitive_samples": candidate.get("ff_sensitive_samples"),
            "rmse_height_m": candidate["rmse_m"],
            "lanes_scored": len(lane_scores),
            "mean_absolute_rise_error_m": (
                round(mean(abs(x["rise_error_m"]) for x in lane_scores), 6)
                if lane_scores else None
            ),
            "lane_rises": lane_scores,
            "measured_segments": sum(
                len(lane["adjacent_normal_checks"]) for lane in lane_summary
            ),
            "segments_scored": len(local_grade_scores),
            "mean_absolute_local_grade_error": (
                round(mean(v["absolute_grade_error"] for v in local_grade_scores), 6)
                if local_grade_scores else None
            ),
            "max_absolute_local_grade_error": (
                max(v["absolute_grade_error"] for v in local_grade_scores)
                if local_grade_scores else None
            ),
            "mean_absolute_normal_grade_error": (
                round(mean(v["absolute_normal_grade_error"] for v in local_grade_scores), 6)
                if local_grade_scores else None
            ),
            "adjacent_grade_segments": local_grade_scores,
            "measured_cross_track_segments": len(cross_track_checks),
            "cross_track_segments_scored": len(cross_grade_scores),
            "mean_absolute_cross_track_grade_error": (
                round(mean(x["absolute_grade_error"] for x in cross_grade_scores), 6)
                if cross_grade_scores else None
            ),
            "cross_track_grade_segments": cross_grade_scores,
            "along_direction_bias": _direction_bias_diagnostic(
                local_grade_scores
            ),
            "cross_direction_bias": _direction_bias_diagnostic(
                cross_grade_scores
            ),
            "measured_patch_segments": (
                sum(len(lane["adjacent_normal_checks"]) for lane in lane_summary)
                + len(cross_track_checks)
            ),
            "patch_segments_scored": len(patch_grade_scores),
            "mean_absolute_patch_grade_error": (
                round(mean(x["absolute_grade_error"] for x in patch_grade_scores), 6)
                if patch_grade_scores else None
            ),
            "mean_absolute_patch_normal_grade_error": (
                round(
                    mean(x["absolute_normal_grade_error"] for x in patch_grade_scores),
                    6,
                ) if patch_grade_scores else None
            ),
        })
    models.sort(key=lambda model: (
        -model["lanes_scored"],
        model["mean_absolute_rise_error_m"]
        if model["mean_absolute_rise_error_m"] is not None
        else float("inf"),
        model["bits"],
        model["lattice_origin_shift_xyz"],
    ))
    return {
        "world_id": observed["world_id"],
        "measured_hits": observed["terrain_surface_hits"],
        "models_evaluated": len(models),
        "six_bit_hypothesis_opted_in": include_six_bit,
        "written_ff_voxels_in_tile": hypotheses.get("written_ff_voxels_in_tile"),
        "lanes": lane_summary,
        "measured_cross_track_segments": len(cross_track_checks),
        "cross_track_normal_checks": cross_track_checks,
        "models_ranked_by_rise_error": models,
        "models_ranked_by_local_grade_error": sorted(models, key=lambda model: (
            -model["segments_scored"],
            model["mean_absolute_local_grade_error"]
            if model["mean_absolute_local_grade_error"] is not None
            else float("inf"),
            model["bits"],
            model["lattice_origin_shift_xyz"],
        )),
        "models_ranked_by_patch_grade_error": sorted(models, key=lambda model: (
            -model["patch_segments_scored"],
            model["mean_absolute_patch_grade_error"]
            if model["mean_absolute_patch_grade_error"] is not None
            else float("inf"),
            model["bits"],
            model["lattice_origin_shift_xyz"],
        )),
        "warning": (
            f"This plan has {len(observed['samples'])} raycast targets and "
            f"{sum(len(lane['adjacent_normal_checks']) for lane in lane_summary)} "
            f"measured along-track segments plus {len(cross_track_checks)} "
            "measured cross-track segments; overlapping segment endpoints "
            "are not independent ground measurements. "
            "Normals and adjacent raycast heights corroborate local terrain "
            "orientation only. Some adjacent pairs may cross triangle edges; "
            "disagreement there is expected. Adjacent-grade scores "
            "exclude segments with missing or ambiguous model roots; "
            "coverage must be considered alongside errors. Directional "
            "mean bias is fitted to these same observations for diagnosis "
            "only; it is NOT a validated tilt correction. These scores "
            "use only the same small region and do not establish "
            "correct voxel packing or actual character walkability."
        ),
    }
