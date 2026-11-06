"""Observed collision-normal / height coplanarity, not saved voxel decoding.

Only game raycasts support these local patches. Similar normals alone do not
prove one triangle: adjacent physics faces can be coplanar.
"""
from __future__ import annotations

from math import acos, degrees, hypot, isfinite, sqrt
from statistics import mean


def _angle_degrees(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    na = sqrt(sum(v * v for v in a))
    nb = sqrt(sum(v * v for v in b))
    if na < 1e-9 or nb < 1e-9:
        return float("inf")
    cosine = sum(x * y for x, y in zip(a, b)) / (na * nb)
    return degrees(acos(max(-1.0, min(1.0, cosine))))


def audit_measured_collision_planes(
    observations: list[dict], *,
    max_link_xy_m: float = 0.51,
    normal_tolerance_degrees: float = 0.1,
    max_plane_residual_m: float = 0.001,
) -> dict:
    """Identify connected, plane-consistent *measured* physics samples.

    Requires three non-collinear XY positions, not just repeated normals.
    No root fitting, private tile bytes, or bridging missing raycasts.
    """
    if not (0 < max_link_xy_m <= 2
            and 0 < normal_tolerance_degrees <= 5
            and 0 < max_plane_residual_m <= 0.1):
        raise ValueError("invalid local collision-plane tolerances")
    valid: list[dict] = []
    for row in observations:
        if row.get("status") != "terrain_surface_hit":
            continue
        xy, z, n = (
            row.get("world_xy"), row.get("actual_z"),
            row.get("normal_world")
        )
        if not (
            isinstance(xy, (tuple, list)) and len(xy) == 2
            and isinstance(n, (tuple, list)) and len(n) == 3
            and all(
                type(v) in (int, float) and isfinite(v)
                for v in (*xy, z if z is not None else float("nan"), *n)
            )
            and n[2] > 0.1
        ):
            continue
        valid.append({
            "index": row["index"],
            "xyz": (float(xy[0]), float(xy[1]), float(z)),
            "normal": tuple(float(v) for v in n),
        })
    links = {r["index"]: set() for r in valid}
    by_id = {r["index"]: r for r in valid}
    if len(by_id) != len(valid):
        raise ValueError("duplicate observed hit indices")
    for i, a in enumerate(valid):
        for b in valid[i + 1:]:
            d = hypot(
                a["xyz"][0] - b["xyz"][0],
                a["xyz"][1] - b["xyz"][1],
            )
            if (
                1e-9 < d <= max_link_xy_m
                and _angle_degrees(
                    a["normal"], b["normal"]
                ) <= normal_tolerance_degrees
            ):
                links[a["index"]].add(b["index"])
                links[b["index"]].add(a["index"])

    groups = []
    seen: set[int] = set()
    for seed in sorted(links):
        if seed in seen:
            continue
        seen.add(seed)
        component = []
        todo = [seed]
        while todo:
            current = todo.pop()
            component.append(current)
            for k in sorted(links[current] - seen):
                seen.add(k)
                todo.append(k)
        if len(component) < 2:
            continue
        ids = sorted(component)
        anchor = by_id[ids[0]]
        ax, ay, az = anchor["xyz"]
        nx, ny, nz = anchor["normal"]
        points = [by_id[i] for i in ids]
        independent_xy = any(
            abs(
                (p["xyz"][0] - ax) * (q["xyz"][1] - ay)
                - (p["xyz"][1] - ay) * (q["xyz"][0] - ax)
            ) > 1e-4
            for p in points for q in points
        )
        angle = max(
            _angle_degrees(anchor["normal"], p["normal"])
            for p in points
        )
        residuals = [
            z - az + (nx * (x - ax) + ny * (y - ay)) / nz
            for p in points for x, y, z in [p["xyz"]]
        ]
        max_error = max(abs(r) for r in residuals)
        supported = (
            independent_xy
            and angle <= normal_tolerance_degrees
            and max_error <= max_plane_residual_m
        )
        groups.append({
            "sample_indices": ids,
            "samples": len(ids),
            "spans_two_xy_directions": independent_xy,
            "max_normal_angle_from_anchor_degrees": round(angle, 6),
            "max_tangent_plane_height_residual_m": round(max_error, 9),
            "rmse_tangent_plane_height_residual_m": round(
                sqrt(mean(r * r for r in residuals)), 9
            ),
            "consistent_sampled_plane": supported,
        })
    return {
        "sampled_ground_hits": len(valid),
        "excluded_non_ground_or_invalid_hits": len(observations) - len(valid),
        "normal_matched_neighbour_pairs": (
            sum(len(x) for x in links.values()) // 2
        ),
        "multi_hit_groups": len(groups),
        "xy_spanning_consistent_groups": sum(
            g["consistent_sampled_plane"] for g in groups
        ),
        "hits_in_xy_spanning_consistent_groups": sum(
            g["samples"] for g in groups if g["consistent_sampled_plane"]
        ),
        "groups": groups,
        "warning": (
            "Only coplanarity of measured game collision points and "
            "normals is tested. Nearby coplanar observations can come "
            "from multiple physics triangles; this is not a reconstructed "
            "mesh, saved voxel decoder, or walkable surface."
        ),
    }
