"""Read-only slope audit of measured terrain against voxel hypotheses.

Raycast point heights and normals provide independent local surface
orientation observations. Neither can establish player capsule clearance.
"""
from __future__ import annotations

from math import hypot
from statistics import mean

from .ground_facet_evidence import audit_measured_collision_planes
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


def _normal_tangent_lateral_holdout(
    observations: list[dict], *, max_anchor_distance_m: float = 1.0,
) -> dict:
    """Predict withheld measured heights from *training-lane* game normals.

    This tests local consistency of the game's OWN observed collision
    points and normals, not a tile decoder. One nearest measured training
    anchor predicts a single held-out point using its tangent plane:
        z = anchor_z - (nx * dx + ny * dy) / nz.
    Never use a held-out normal/height to make that prediction. Neither
    nearby-game-normal success nor a small residual establishes novel
    terrain geometry or clearance. No raycasts are bridged over gaps.
    """
    from math import isfinite, sqrt
    from statistics import median

    if not 0 < max_anchor_distance_m <= 4:
        raise ValueError("max normal anchor distance must be in (0, 4]")
    lanes = set()
    for row in observations:
        lane = row.get("lateral_offset_m")
        if type(lane) not in (int, float) or not isfinite(lane):
            return {"status": "unavailable_track_metadata", "folds": []}
        lanes.add(float(lane))
    if len(lanes) < 3:
        return {
            "status": "insufficient_distinct_tracks",
            "distinct_tracks": len(lanes),
            "folds": [],
        }

    def measured(row: dict) -> bool:
        return row["status"] == "terrain_surface_hit"

    def valid_normal(row: dict) -> bool:
        n = row.get("normal_world")
        return (
            isinstance(n, (list, tuple)) and len(n) == 3
            and all(type(v) in (float, int) and isfinite(v) for v in n)
            and n[2] > 0.1
        )

    folds = []
    for offset in sorted(lanes):
        train = [r for r in observations
                 if float(r["lateral_offset_m"]) != offset and measured(r)]
        held = [r for r in observations
                if float(r["lateral_offset_m"]) == offset]
        ground = [r for r in held if measured(r)]
        anchors = [r for r in train if valid_normal(r)]
        paired = []
        too_far_or_invalid = 0
        for target in ground:
            x, y = target["world_xy"]
            if not anchors:
                too_far_or_invalid += 1
                continue
            nearest = min(anchors, key=lambda source: (
                (source["world_xy"][0] - x) ** 2
                + (source["world_xy"][1] - y) ** 2,
                source["index"],
            ))
            ax, ay = nearest["world_xy"]
            distance = hypot(x - ax, y - ay)
            if distance > max_anchor_distance_m:
                too_far_or_invalid += 1
                continue
            nx, ny, nz = nearest["normal_world"]
            estimated = nearest["actual_z"] - (nx * (x - ax) + ny * (y - ay)) / nz
            paired.append((target["actual_z"], estimated, nearest["actual_z"]))

        def rmse(errors: list[float]) -> float | None:
            return round(sqrt(mean(e * e for e in errors)), 6) if errors else None

        flat_height = median(r["actual_z"] for r in train) if train else None
        model_errors = [pred - actual for actual, pred, _ in paired]
        flat_errors = (
            [flat_height - actual for actual, _, _ in paired]
            if flat_height is not None else []
        )
        nearest_errors = [z - actual for actual, _, z in paired]
        folds.append({
            "held_out_lateral_offset_m": offset,
            "status": (
                "scored" if paired else
                "no_valid_training_anchor_or_normal"
                if ground else "no_held_out_ground_hits"
            ),
            "planned_targets": len(held),
            "held_out_game_hits": len(ground),
            "missing_held_out_game_hits": len(held) - len(ground),
            "training_game_hits": len(train),
            "training_valid_normals": len(anchors),
            "held_out_scored": len(paired),
            "no_eligible_anchor": too_far_or_invalid,
            "max_anchor_distance_m": max_anchor_distance_m,
            "normal_tangent_rmse_m": rmse(model_errors),
            "nearest_anchor_height_rmse_m": rmse(nearest_errors),
            "training_median_flat_rmse_m": rmse(flat_errors),
        })
    return {
        "status": (
            "within_site_diagnostic_only"
            if all(f["status"] == "scored"
                   and f["missing_held_out_game_hits"] == 0
                   and f["no_eligible_anchor"] == 0 for f in folds)
            else "incomplete_within_site_diagnostic"
        ),
        "distinct_tracks": len(lanes),
        "folds": folds,
        "warning": (
            "Uses only *observed game normals and heights* on other nearby "
            "lanes, not values predicted from saved tile bytes. A normal "
            "at a training point predicts only the local tangent plane at "
            "a held-out point. Predictions are limited by anchor distance, "
            "exclude misses, and are scored against measured game hits. "
            "All lanes come from the same small cave patch: this does NOT "
            "validate a voxel decoder, independently held-out terrain, "
            "character clearance, or a traversable route."
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
        "measured_collision_plane_evidence": audit_measured_collision_planes(
            observed["samples"]
        ),
        "normal_tangent_lateral_holdout": _normal_tangent_lateral_holdout(
            observed["samples"]
        ),
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
            "correct voxel packing or actual character walkability. "
            "The separate normal tangent holdout evaluates GAME normals "
            "on nearby measured points, NOT a saved tile decoder. "
            "The measured collision plane evidence describes coherent "
            "sampled game physics facets, not reconstructed triangles."
        ),
    }
