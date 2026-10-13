from __future__ import annotations

from copy import deepcopy

from scripts.verify_browser_parity import compare_reports


def example_report() -> dict:
    return {
        "worlds": [
            {"id": 1, "kind": "overworld", "depth": None, "label": "Overworld"},
            {"id": 12, "kind": "underground", "depth": 1, "label": "D1 Mine"},
        ],
        "portals": {"count": 3, "resolved": 2},
        "underground": [
            {
                "worldId": 12, "rowId": 99, "status": "tunnels",
                "tunnels": 2, "caveCells": 4, "pocketCells": 6,
                "caveGroups": 1, "pocketGroups": 3,
                "pocketGroupsComplete": 2, "pocketGroupsSplit": 1,
                "points": 20,
                "tunnelDigest": "a" * 64,
                "placementDigest": "b" * 64,
            },
        ],
    }


def test_parity_accepts_exact_match() -> None:
    sample = example_report()
    assert compare_reports(sample, deepcopy(sample)) == []


def test_parity_detects_geometry_differences_even_if_counts_match() -> None:
    expected = example_report()
    actual = deepcopy(expected)
    actual["underground"][0]["tunnelDigest"] = "c" * 64
    actual["underground"][0]["placementDigest"] = "d" * 64
    assert compare_reports(expected, actual) == [
        "Underground world 12: tunnelDigest mismatch",
        "Underground world 12: placementDigest mismatch",
    ]


def test_parity_rejects_world_or_portal_drift() -> None:
    expected = example_report()
    actual = deepcopy(expected)
    actual["portals"]["resolved"] = 1
    actual["underground"].clear()
    messages = compare_reports(expected, actual)
    assert "Portal totals or resolution mismatch" in messages
    assert "Underground world ID set mismatch" in messages


def test_parity_detects_source_grouping_drift_with_matching_raw_footprint_counts() -> None:
    expected = example_report()
    actual = deepcopy(expected)
    actual["underground"][0]["pocketGroups"] = 6
    actual["underground"][0]["pocketGroupsSplit"] = 0
    assert compare_reports(expected, actual) == [
        "Underground world 12: pocketGroups mismatch",
        "Underground world 12: pocketGroupsSplit mismatch",
    ]
