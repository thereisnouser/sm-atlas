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


def audit_ground_slopes(plan: dict, log: str, tile) -> dict:
    """Compare observed grades to normals and modelled end-to-end rises.

    Scores only end-to-end lane rises with two actual upward hits and
    unambiguous single model roots at both endpoints. Does not promote
    a model based on artificially small height residuals.
    """
    observed = compare_ground_observations(plan, log)
    hypotheses = compare_trilinear_hypotheses(plan, log, tile)

    lane_summary = []
    for lateral, lane in _lane_rows(observed["samples"]):
        valid = [r for r in lane if r["status"] == "terrain_surface_hit"]
        # Avoid bridging a missing observation to infer local normals.
        normal_checks = []
        for a, b in zip(lane, lane[1:]):
            if (a["status"] != "terrain_surface_hit"
                    or b["status"] != "terrain_surface_hit"):
                continue
            dx = b["world_xy"][0] - a["world_xy"][0]
            dy = b["world_xy"][1] - a["world_xy"][1]
            span = hypot(dx, dy)
            if span <= 1e-9:
                continue
            actual_grade = (b["actual_z"] - a["actual_z"]) / span
            ux, uy = dx / span, dy / span
            # Average endpoint normal-derived directional grades.
            estimates = [
                -(r["normal_world"][0] * ux
                  + r["normal_world"][1] * uy)
                / r["normal_world"][2]
                for r in (a, b)
                if abs(r["normal_world"][2]) > 0.1
            ]
            if not estimates:
                continue
            estimated_grade = mean(estimates)
            normal_checks.append({
                "from_index": a["index"],
                "to_index": b["index"],
                "horizontal_span_m": round(span, 6),
                "observed_directional_grade": round(actual_grade, 6),
                "normal_implied_directional_grade": round(estimated_grade, 6),
                "absolute_disagreement": round(
                    abs(actual_grade - estimated_grade), 6
                ),
            })
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
                first = rows.get(segment["from_index"])
                last = rows.get(segment["to_index"])
                if (first is None or last is None
                        or first["status"] != "single_candidate"
                        or last["status"] != "single_candidate"):
                    continue
                span = segment["horizontal_span_m"]
                if span <= 0:
                    continue
                model_grade = (
                    last["candidate_world_z"][0]
                    - first["candidate_world_z"][0]
                ) / span
                measured_grade = segment["observed_directional_grade"]
                normal_grade = segment["normal_implied_directional_grade"]
                local_grade_scores.append({
                    "from_index": segment["from_index"],
                    "to_index": segment["to_index"],
                    "lateral_offset_m": lane["lateral_offset_m"],
                    "horizontal_span_m": span,
                    "observed_directional_grade": measured_grade,
                    "normal_implied_directional_grade": normal_grade,
                    "model_directional_grade": round(model_grade, 6),
                    "absolute_grade_error": round(
                        abs(model_grade - measured_grade), 6
                    ),
                    "absolute_normal_grade_error": round(
                        abs(model_grade - normal_grade), 6
                    ),
                })
        models.append({
            "bits": candidate["bits"],
            "lattice_origin_shift_xyz": candidate["lattice_origin_shift_xyz"],
            "single_candidates": candidate["single_candidates"],
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
        "lanes": lane_summary,
        "models_ranked_by_rise_error": models,
        "models_ranked_by_local_grade_error": sorted(models, key=lambda model: (
            -model["segments_scored"],
            model["mean_absolute_local_grade_error"]
            if model["mean_absolute_local_grade_error"] is not None
            else float("inf"),
            model["bits"],
            model["lattice_origin_shift_xyz"],
        )),
        "warning": (
            "Normals and adjacent raycast heights corroborate local terrain "
            "orientation only. Some adjacent pairs may cross triangle edges; "
            "disagreement there is expected. Adjacent-grade scores "
            "exclude segments with missing or ambiguous model roots; "
            "coverage must be considered alongside errors. These scores "
            "use only the same small region and do not establish "
            "correct voxel packing or actual character walkability."
        ),
    }
