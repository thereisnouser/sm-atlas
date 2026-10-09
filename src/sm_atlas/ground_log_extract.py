"""Extract a single plan-verified physics probe run from a full game log.

A raw Scrap Mechanic log can contain multiple probes, old experiments and
unrelated Lua messages. Never merge observations across probe markers or
silently fall back to an earlier run after the newest matching run fails.
"""
from __future__ import annotations

import re

from .ground_truth import (
    LOG_PREFIX,
    _validated_ground_plan,
    compare_ground_observations,
)


META_PREFIX = "ATLAS_GROUND_META,"
_META_PATTERN = re.compile(r"ATLAS_GROUND_META,world=([0-9]+),count=([0-9]+)")


def extract_ground_probe_run(plan: dict, game_log: str) -> tuple[str, dict]:
    """Return the latest matching complete run and its validation summary.

    The generated Lua announces each probe with ATLAS_GROUND_META before
    emitting point records. The latest marker with this world's ID and
    the plan's point count is authoritative. If that run is incomplete
    or invalid, reject it rather than selecting older measurements.

    Legacy logs without metadata can still be checked manually using
    tile-ground-compare; automatic extraction deliberately requires it.
    """
    world_id, samples = _validated_ground_plan(plan)
    expected_count = len(samples)
    markers_seen = 0
    matching_runs: list[dict] = []
    active: dict | None = None

    for line_number, line in enumerate(game_log.splitlines(), start=1):
        meta_pos = line.find(META_PREFIX)
        if meta_pos >= 0:
            payload = line[meta_pos:].strip()
            match = _META_PATTERN.fullmatch(payload)
            if match is None:
                raise ValueError(
                    f"invalid ATLAS_GROUND_META marker at line {line_number}"
                )
            markers_seen += 1
            found_world, found_count = map(int, match.groups())
            active = None
            if found_world == world_id and found_count == expected_count:
                active = {
                    "marker_line": line_number,
                    "marker_number": markers_seen,
                    "lines": [],
                }
                matching_runs.append(active)
            continue

        record_pos = line.find(LOG_PREFIX)
        if active is not None and record_pos >= 0:
            active["lines"].append(line[record_pos:].strip())

    if not markers_seen:
        raise ValueError(
            "no ATLAS_GROUND_META markers found in game log; "
            "automatic extraction requires a generated Lua probe with "
            "run metadata (legacy single-run logs can use tile-ground-compare)"
        )
    if not matching_runs:
        raise ValueError(
            f"no probe marker matches world={world_id},"
            f"count={expected_count}; check the plan and game log"
        )

    selected = matching_runs[-1]
    records = selected["lines"]
    if len(records) != expected_count:
        raise ValueError(
            f"newest matching probe at log line {selected['marker_line']} "
            f"has {len(records)}/{expected_count} records; refusing to "
            "merge runs or silently use older measurements"
        )
    extracted = "\n".join(records) + "\n"
    # Reuse the exact validation performed by every downstream analysis:
    # all point indices, world IDs, XY and planned Z must match this plan.
    comparison = compare_ground_observations(plan, extracted)
    if comparison["not_sampled"] != 0:
        raise ValueError(
            "latest matching probe does not contain every planned index"
        )
    return extracted, {
        "world_id": world_id,
        "expected_points": expected_count,
        "extracted_records": len(records),
        "game_ground_hits": comparison["terrain_surface_hits"],
        "other_hits_or_misses": comparison["other_hits_or_misses"],
        "matching_runs_found": len(matching_runs),
        "total_probe_markers_found": markers_seen,
        "selected_marker_line": selected["marker_line"],
        "selected_marker_number": selected["marker_number"],
        "warning": (
            "Raycast hits are physics observations, not proof of player "
            "walkability. Source log and original plan remain unchanged."
        ),
    }
