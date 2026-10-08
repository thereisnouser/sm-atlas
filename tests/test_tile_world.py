from __future__ import annotations

from dataclasses import replace

import pytest

from sm_atlas.tile_world import (
    _edge_measurement_samples,
    _match_saved_tunnels,
    _parse_edge_coordinate,
    _verify_placement,
    tile_to_world,
    world_to_tile,
)
from sm_atlas.underground_topology import LayoutNode


def _node(rotation: int = 1) -> LayoutNode:
    return LayoutNode(
        node_id=322,
        kind="pocket",
        name="drill2_tunnelpocket_small_passage_08_2x3x2.tile",
        family="tunnel_pocket",
        tags=("passage",),
        min_x=32, max_x=80,
        min_y=-112, max_y=-80,
        min_z=64, max_z=96,
        tile_uuid="a7bde4a1-89f1-4493-8331-270ba1dae561",
        rotation=rotation,
    )


def test_saved_world_23_two_socket_world_coordinates() -> None:
    node = _node()
    dims = (32, 48, 32)

    # Independent anchor coordinates observed in the saved tunnel graph.
    local_socket7 = (29.333333333, 8.0, 8.0)
    local_socket6 = (2.666666667, 40.0, 24.0)

    assert tile_to_world(node, dims, local_socket7) == pytest.approx(
        (72.0, -82.666666667, 72.0), abs=1e-6,
    )
    assert tile_to_world(node, dims, local_socket6) == pytest.approx(
        (40.0, -109.333333333, 88.0), abs=1e-6,
    )

    assert tile_to_world(node, dims, (4, 35, 19)) == (
        45.0, -108.0, 83.0
    )
    assert tile_to_world(node, dims, (3, 35, 20)) == (
        45.0, -109.0, 84.0
    )


@pytest.mark.parametrize(
    "rotation,dimensions,bounds",
    [
        (0, (32, 48, 32), (32, 48)),
        (1, (32, 48, 32), (48, 32)),
        (2, (32, 48, 32), (32, 48)),
        (3, (32, 48, 32), (48, 32)),
    ],
)
def test_tile_world_transform_round_trips_all_quarter_turns(
    rotation: int,
    dimensions: tuple[int, int, int],
    bounds: tuple[int, int],
) -> None:
    node = replace(
        _node(), rotation=rotation,
        max_x=32 + bounds[0],
        max_y=-112 + bounds[1],
    )
    for point in ((0, 0, 0), (3.125, 17.25, 9.5), (32, 48, 32)):
        transformed = tile_to_world(node, dimensions, point)
        assert world_to_tile(node, dimensions, transformed) == (
            pytest.approx(point, abs=1e-9)
        )


def test_tile_placement_rejects_wrong_uuid_and_bounds() -> None:
    node = _node()
    _verify_placement(
        node, (32, 48, 32),
        "a7bde4a1-89f1-4493-8331-270ba1dae561",
    )
    with pytest.raises(ValueError, match="UUID"):
        _verify_placement(node, (32, 48, 32), "f" * 32)
    with pytest.raises(ValueError, match="bounds"):
        _verify_placement(node, (32, 47, 32), node.tile_uuid)


def test_saved_tunnel_endpoints_anchor_two_independent_sockets() -> None:
    node = _node()
    dims = (32, 48, 32)
    sockets = [
        {
            "socket": "cell0:node7",
            "world_position": tile_to_world(
                node, dims, (29.333333333, 8, 8),
            ),
        },
        {
            "socket": "cell0:node6",
            "world_position": tile_to_world(
                node, dims, (2.666666667, 40, 24),
            ),
        },
    ]
    tunnels = [
        {
            "id": 42,
            "type": "TtVeinRich",
            "points": [(100, 0, 0), (72, -82.666667, 72)],
        },
        {
            "id": 269,
            "type": "TtVeinSparkstone",
            "points": [(40, -109.333333, 88), (0, 0, 0)],
        },
    ]
    matches = _match_saved_tunnels(
        sockets, tunnels, tolerance_m=0.25,
    )
    assert {(m["tunnel_id"], m["socket"]) for m in matches} == {
        (42, "cell0:node7"),
        (269, "cell0:node6"),
    }
    assert max(m["residual_m"] for m in matches) < 0.00001

    assert _match_saved_tunnels(
        sockets, tunnels, tolerance_m=0.000000001,
    ) == []


def test_nearby_ambiguous_socket_is_not_used_as_alignment_proof() -> None:
    sockets = [
        {"socket": "first", "world_position": (10.0, 0.0, 0.0)},
        {"socket": "second", "world_position": (10.2, 0.0, 0.0)},
    ]
    tunnels = [{
        "id": 1, "type": "test",
        "points": [(10.1, 0.0, 0.0), (50.0, 0.0, 0.0)],
    }]
    assert _match_saved_tunnels(
        sockets, tunnels, tolerance_m=0.15,
    ) == []


def test_edge_samples_map_xy_at_quarter_metre_intervals() -> None:
    node = replace(
        _node(),
        min_x=10, max_x=12,
        min_y=20, max_y=22,
        min_z=30, max_z=33,
    )
    dims = (2, 2, 3)
    volume = bytearray([0] * (2 * 2 * 3))
    for x in range(2):
        for y in range(2):
            volume[(x * 2 + y) * 3] = 31 if x == 0 else 16

    result = _edge_measurement_samples(
        node, dims, volume,
        ((0, 0, 1), (1, 0, 1)),
        density_bits=5, density_threshold=16,
    )
    assert result["estimated_absolute_gradient"] == pytest.approx(
        15 / 31, abs=1e-6,
    )
    assert len(result["world_samples"]) == 15
    center_track = [
        item for item in result["world_samples"]
        if item["lateral_offset_m"] == 0
    ]
    assert center_track[0]["world_xy"] == (11.5, 20.5)
    assert center_track[1]["world_xy"] == (11.5, 20.75)
    assert center_track[-1]["world_xy"] == (11.5, 21.5)
    assert result["endpoints"][0]["world_foot_voxel_reference"] == [
        11.5, 20.5, 31.0,
    ]


def test_invalid_measurement_edge_is_rejected() -> None:
    node = replace(
        _node(), min_x=0, max_x=2, min_y=0, max_y=2,
        min_z=0, max_z=3,
    )
    volume = bytearray([0] * 12)
    with pytest.raises(ValueError, match="cardinal"):
        _edge_measurement_samples(
            node, (2, 2, 3), volume,
            ((0, 0, 1), (1, 1, 1)),
            density_bits=5, density_threshold=16,
        )
    with pytest.raises(ValueError, match="iso-crossing"):
        _edge_measurement_samples(
            node, (2, 2, 3), volume,
            ((0, 0, 1), (1, 0, 1)),
            density_bits=5, density_threshold=16,
        )


def test_tile_world_cli_accepts_save_and_edge() -> None:
    from sm_atlas.cli import build_parser

    args = build_parser().parse_args([
        "tile-world-probe", "save.db", "tile.tile",
        "--world", "23", "--node", "322",
        "--edge", "4,35,19", "3,35,20",
        "--json",
    ])
    assert args.save.name == "save.db"
    assert args.tile.name == "tile.tile"
    assert args.world == 23
    assert args.node == 322
    assert args.edge == ["4,35,19", "3,35,20"]
    assert args.density_bits == 5
    assert args.json is True


def test_edge_coordinate_parser_is_strict() -> None:
    assert _parse_edge_coordinate("4,35,19") == (4, 35, 19)
    for raw in ("4,35", "a,35,19", "4.0,35,19"):
        with pytest.raises(ValueError, match="edge points"):
            _parse_edge_coordinate(raw)
