from __future__ import annotations

from array import array

import pytest

from sm_atlas.tile_voxel_walk import (
    _candidate_foot_positions,
    _explain_component_gap,
    _socket_inward_profile,
    _straight_candidate_space,
    _label_walk_components,
    _shortest_walk,
    probe_tile_voxel_walk,
)


def _stepped_tunnel() -> tuple[bytearray, tuple[int, int, int]]:
    dims = (5, 1, 4)
    volume = bytearray([31] * 20)
    for x in range(5):
        foot_z = 1 if x < 2 else 2
        for z in (foot_z, foot_z + 1):
            volume[(x * dims[1]) * dims[2] + z] = 0
    return volume, dims


def test_candidate_footpath_connects_one_meter_step() -> None:
    volume, dims = _stepped_tunnel()
    footprint = _candidate_foot_positions(
        volume, dims, threshold=8, headroom=2,
    )
    labels, groups = _label_walk_components(
        footprint, dims, max_step=1,
    )
    assert len(groups) == 1
    assert groups[0]["voxels"] == 5

    route = _shortest_walk(
        (0, 0, 1), (4, 0, 2), footprint, dims, max_step=1,
    )
    assert route is not None
    assert route["grid_steps"] == 4
    assert route["length_m"] == pytest.approx(3 + 2**0.5, abs=0.001)
    assert route["climb_m"] == 1
    assert route["descent_m"] == 0


def test_no_steps_splits_height_change() -> None:
    volume, dims = _stepped_tunnel()
    footprint = _candidate_foot_positions(
        volume, dims, threshold=8, headroom=2,
    )
    _, groups = _label_walk_components(
        footprint, dims, max_step=0,
    )
    assert sorted(c["voxels"] for c in groups) == [2, 3]
    assert _shortest_walk(
        (0, 0, 1), (4, 0, 2), footprint, dims, max_step=0,
    ) is None


def test_missing_support_and_headroom_are_not_walkable() -> None:
    volume = bytearray([31, 0, 31, 0, 0])
    footprint = _candidate_foot_positions(
        volume, (1, 1, 5), threshold=8, headroom=2,
    )
    assert footprint.count(1) == 1
    assert footprint[3] == 1


def test_validate_parameters_without_reading_tile(tmp_path) -> None:
    path = tmp_path / "room_1x1x1.tile"
    with pytest.raises(ValueError, match="headroom"):
        probe_tile_voxel_walk(path, headroom=0)
    with pytest.raises(ValueError, match="max_step"):
        probe_tile_voxel_walk(path, max_step=3)
    with pytest.raises(ValueError, match="both from_socket"):
        probe_tile_voxel_walk(path, from_socket="cell0:node1")



def test_uphill_transition_requires_clearance_above_lower_head() -> None:
    # The higher floor's standing cells are clear, but the low-side
    # ceiling obstructs a full-height actor during a one-metre ascent.
    dims = (2, 1, 5)
    volume = bytearray([31] * 10)
    for index in (1, 2, 7, 8):
        volume[index] = 0

    footprint = _candidate_foot_positions(
        volume, dims, threshold=8, headroom=2,
    )
    assert footprint.count(1) == 2

    # Historical endpoint-only edge rule incorrectly connected the floors.
    assert _shortest_walk(
        (0, 0, 1), (1, 0, 2), footprint, dims, max_step=1,
    ) is not None

    labels, groups = _label_walk_components(
        footprint, dims, max_step=1, volume=volume, headroom=2,
    )
    assert len(groups) == 2
    assert sorted(group["voxels"] for group in groups) == [1, 1]
    assert _shortest_walk(
        (0, 0, 1), (1, 0, 2), footprint, dims,
        max_step=1, volume=volume, headroom=2,
    ) is None
    # The reverse edge is also rejected; floor components are undirected.
    assert _shortest_walk(
        (1, 0, 2), (0, 0, 1), footprint, dims,
        max_step=1, volume=volume, headroom=2,
    ) is None

    # Removing the ceiling obstacle makes the transition a valid candidate.
    volume[3] = 0
    path = _shortest_walk(
        (0, 0, 1), (1, 0, 2), footprint, dims,
        max_step=1, volume=volume, headroom=2,
    )
    assert path is not None
    assert path["rise_clearance_checked"] is True
    assert path["rise_steps"] == 1
    assert path["drop_steps"] == 0
    assert path["unverified_elevation_edges"] == 1


def test_component_gap_reports_two_metre_step() -> None:
    dims = (2, 1, 5)
    labels = array("I", [0] * 10)
    labels[2] = 9  # left floor z=2
    labels[5] = 85  # right floor z=0

    gap = _explain_component_gap(
        labels, dims, 9, 85,
        max_step=1,
        volume=bytearray([31] * 10),
        density_threshold=8,
        headroom=2,
    )

    assert gap["reason_counts"] == {"step_exceeds_limit": 1}
    assert gap["closest_adjacent_candidate"]["from_foot"] == (0, 0, 2)
    assert gap["closest_adjacent_candidate"]["to_foot"] == (1, 0, 0)


def test_component_gap_reports_low_side_ceiling_blocker() -> None:
    dims = (2, 1, 5)
    volume = bytearray([31] * 10)
    for index in (1, 2, 7, 8):
        volume[index] = 0

    footprint = _candidate_foot_positions(
        volume, dims, threshold=8, headroom=2,
    )
    labels, groups = _label_walk_components(
        footprint, dims, max_step=1, volume=volume,
        headroom=2,
    )
    assert len(groups) == 2

    gap = _explain_component_gap(
        labels, dims, 1, 2,
        max_step=1, volume=volume,
        density_threshold=8, headroom=2,
    )
    assert gap["reason_counts"] == {"low_side_headroom_blocked": 1}
    blocker = gap["examples"]["low_side_headroom_blocked"][0]["blocker"]
    assert blocker == {
        "position": (0, 0, 3),
        "raw": 31,
        "density": 15,
    }


def test_socket_entrance_profile_records_solid_surface_then_void() -> None:
    dims = (8, 5, 5)
    # x=2 -> solid shell, x=3-4 -> air, x=5 -> second wall.
    volume = bytearray([31] * (8 * 5 * 5))
    for x in (3, 4):
        volume[(x * 5 + 2) * 5 + 2] = 0
    # x- (distance 2m) is strictly closer than either y edge (2.5m).
    # Keep floor(x, y, z) == (2, 2, 2) for the voxel fixture.
    profile = _socket_inward_profile(
        (2.0, 2.5, 2.0),
        volume, dims, threshold=8, sample_cells=5,
    )

    assert profile["face"] == "x-"
    assert profile["first_open_voxel"] == (3, 2, 2)
    assert profile["first_open_offset_cells"] == 1
    assert profile["reblocked_after_first_open"] is True
    assert [sample["raw"] for sample in profile["samples"]] == [
        31, 0, 0, 31, 31
    ]


def test_socket_entrance_profile_handles_positive_edge() -> None:
    dims = (8, 5, 5)
    volume = bytearray([31] * (8 * 5 * 5))
    volume[(5 * 5 + 2) * 5 + 2] = 0
    profile = _socket_inward_profile(
        (6.333, 2.0, 2.0),
        volume, dims, threshold=8, sample_cells=3,
    )
    assert profile["face"] == "x+"
    assert profile["first_open_offset_cells"] == 1
    assert profile["first_open_voxel"] == (5, 2, 2)


def test_candidate_centreline_reports_first_solid_intersection() -> None:
    dims = (1, 1, 5)
    volume = bytearray((0, 0, 111, 0, 0))
    result = _straight_candidate_space(
        (0, 0, 0), (0, 0, 4), volume, dims, threshold=8,
    )
    assert result == {
        "status": "candidate_solid_intersection",
        "first_blocker": {"voxel": (0, 0, 2), "raw": 111, "density": 15},
    }

    volume[2] = 0
    assert _straight_candidate_space(
        (0, 0, 0), (0, 0, 4), volume, dims, threshold=8,
    ) == {"status": "clear_centreline", "first_blocker": None}


def test_socket_inward_profile_uses_actual_closest_face() -> None:
    dims = (8, 5, 5)
    volume = bytearray([31] * (8 * 5 * 5))
    # y- is 1m away and x- is 2.667m away.
    profile = _socket_inward_profile(
        (2.667, 1.0, 2.0),
        volume, dims, threshold=8, sample_cells=2,
    )
    assert profile["face"] == "y-"
    assert [sample["voxel"] for sample in profile["samples"]] == [
        (2, 1, 2),
        (2, 2, 2),
    ]
