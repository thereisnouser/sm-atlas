from __future__ import annotations

import pytest

from sm_atlas.ground_isovalue_audit import (
    _density_at_observed_hit,
    audit_observed_isovalues,
)


def _volume():
    dims = (4, 4, 6)
    volume = bytearray([0]) * (dims[0] * dims[1] * dims[2])
    written = bytearray([1]) * len(volume)
    for x in range(4):
        for y in range(4):
            for z in range(6):
                volume[(x * 4 + y) * 6 + z] = 15 if z <= 2 else 0
    return volume, dims, written


def _profile_and_bytes(monkeypatch):
    from sm_atlas import ground_isovalue_audit as module
    volume, dims, written = _volume()
    # Three different game rays at the actual 4-bit threshold intersection.
    z_hit = 2 + 7 / 15
    samples = [
        {"index": i, "local_xyz": [x, y, z_hit]}
        for i, (x, y) in enumerate((
            (1.25, 1.25), (1.5, 1.75), (1.75, 1.5),
        ))
    ]
    monkeypatch.setattr(
        module, "inspect_ground_density",
        lambda plan, log, tile: {
            "world_id": 23, "tile_path": "synthetic_1x1x1.tile",
            "samples": samples,
        },
    )
    monkeypatch.setattr(module, "_dimensions", lambda path: dims)
    monkeypatch.setattr(
        module, "_load_density_bytes",
        lambda path, dimensions, *, return_written=False: (
            (volume, 0, written) if return_written else (volume, 0)
        ),
    )
    return volume, dims, written


def test_actual_hit_density_matches_fixed_four_bit_midpoint(monkeypatch):
    _profile_and_bytes(monkeypatch)
    result = audit_observed_isovalues({}, "", "dummy.tile")
    assert result["models_evaluated"] == 16
    assert result["six_bit_hypothesis_opted_in"] is False
    model = next(m for m in result["models"] if (
        m["bits"] == 4 and m["lattice_origin_shift_xyz"] == [0, 0, 0]
    ))
    assert model["samples_scored"] == 3
    assert model["falling_density_samples"] == 3
    assert model["flat_density_samples"] == 0
    assert model["rising_density_samples"] == 0
    assert model["mean_abs_distance_from_fixed_midpoint"] == pytest.approx(
        0, abs=1e-6,
    )
    assert model["mean_abs_spread_around_sample_median"] == 0
    other = next(m for m in result["models"] if (
        m["bits"] == 5 and m["lattice_origin_shift_xyz"] == [0, 0, 0]
    ))
    assert other["mean_abs_distance_from_fixed_midpoint"] > 0.20
    assert other["falling_density_samples"] == 3


def test_six_bit_option_and_no_fake_density_in_absent_voxel(monkeypatch):
    volume, dims, written = _profile_and_bytes(monkeypatch)
    missing = (1 * dims[1] + 1) * dims[2] + 3
    written[missing] = 0
    report = audit_observed_isovalues(
        {}, "", "dummy.tile", include_six_bit=True,
    )
    assert report["models_evaluated"] == 24
    assert report["six_bit_hypothesis_opted_in"] is True
    m = next(m for m in report["models"] if (
        m["bits"] == 4 and m["lattice_origin_shift_xyz"] == [0, 0, 0]
    ))
    assert m["samples_scored"] == 0
    assert m["samples_expected"] == 3
    assert m["median_observed_normalized_density"] is None
    assert m["mean_abs_spread_around_sample_median"] is None


def test_density_at_actual_hit_does_not_interpret_missing_as_ff():
    volume, dims, written = _volume()
    local = [1.5, 1.5, 2 + 7 / 15]
    result = _density_at_observed_hit(
        volume, dims, written, local, mask=15,
        shift_xyz=(0.0, 0.0, 0.0),
    )
    assert result is not None
    density, rise = result
    assert density == pytest.approx(8)
    assert rise == pytest.approx(-15)
    idx = (1 * dims[1] + 1) * dims[2] + 3
    written[idx] = 0
    assert _density_at_observed_hit(
        volume, dims, written, local, mask=15,
        shift_xyz=(0.0, 0.0, 0.0),
    ) is None


def test_uniform_density_has_zero_spread_but_no_surface_evidence(monkeypatch):
    volume, dims, written = _profile_and_bytes(monkeypatch)
    volume[:] = bytearray([15]) * len(volume)
    report = audit_observed_isovalues({}, "", "dummy.tile")
    m = next(m for m in report["models"] if (
        m["bits"] == 4 and m["lattice_origin_shift_xyz"] == [0, 0, 0]
    ))
    assert m["mean_abs_spread_around_sample_median"] == 0
    assert m["falling_density_samples"] == 0
    assert m["flat_density_samples"] == 3
    assert m["mean_abs_distance_from_fixed_midpoint"] > 0.4


def test_cli_isovalue_flags_are_explicit_and_read_only():
    from sm_atlas.cli import build_parser
    parser = build_parser()
    cmd = [
        "tile-ground-isovalue-audit",
        "ground_plan.json", "atlas_ground_hits.log", "sample.tile",
    ]
    old = parser.parse_args(cmd)
    new = parser.parse_args(cmd + ["--include-6-bit", "--json"])
    assert old.include_6_bit is False
    assert new.include_6_bit is True
    assert new.json is True
