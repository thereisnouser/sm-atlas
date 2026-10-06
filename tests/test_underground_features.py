from __future__ import annotations

from sm_atlas.formats.lua_values import LuaQuat, LuaVec3
from sm_atlas.underground_features import (
    CHUNK_SIZE_METERS,
    CELL_SIZE_METERS,
    _decode_cave,
    _decode_pocket,
    extract_spawners,
)


def test_decode_cave_piece() -> None:
    raw = (
        6
        | (7 << 8)
        | (5 << 12)
        | (2 << 16)
        | (1 << 18)
        | (3 << 20)
    )

    piece = _decode_cave(
        raw,
        cell_x=-2,
        cell_y=-3,
        tile_lookup={6: "tile-six"},
    )

    assert piece.kind == "cave"
    assert piece.tile_index == 6
    assert piece.tile_uuid == "tile-six"
    assert piece.x == -2 * CELL_SIZE_METERS
    assert piece.y == -3 * CELL_SIZE_METERS
    assert piece.z == 7 * CHUNK_SIZE_METERS
    assert piece.width == CELL_SIZE_METERS
    assert piece.depth == CELL_SIZE_METERS
    assert piece.height == 6 * CHUNK_SIZE_METERS
    assert piece.rotation == 3
    assert piece.source_x == 8
    assert piece.source_y == 4


def test_decode_pocket_piece_and_rotation() -> None:
    placement = 2 | (1 << 2) | (5 << 4)
    packed_size = 1 | (2 << 2) | (3 << 4)
    raw = (
        9
        | (placement << 8)
        | (packed_size << 16)
        | (3 << 24)
        | (2 << 26)
        | (1 << 28)
    )

    piece = _decode_pocket(
        raw,
        cell_x=1,
        cell_y=-2,
        tile_lookup={9: "tile-nine"},
    )

    assert piece.kind == "pocket"
    assert piece.tile_index == 9
    assert piece.tile_uuid == "tile-nine"
    assert piece.x == CELL_SIZE_METERS + 2 * CHUNK_SIZE_METERS
    assert piece.y == -2 * CELL_SIZE_METERS + CHUNK_SIZE_METERS
    assert piece.z == 5 * CHUNK_SIZE_METERS

    # Packed size is 2 x 3 chunks; odd rotation swaps the footprint axes.
    assert piece.width == 3 * CHUNK_SIZE_METERS
    assert piece.depth == 2 * CHUNK_SIZE_METERS
    assert piece.height == 4 * CHUNK_SIZE_METERS
    assert piece.rotation == 1
    assert piece.source_x == 3
    assert piece.source_y == 2


def test_extract_spawners_uses_cell_local_position() -> None:
    value = {
        "spawners": {
            -6: {
                -3: {
                    1: {
                        "scale": LuaVec3(48.0, 48.0, 48.0),
                        "tags": {
                            1: "SPAWN_ENEMY_VOLUME_TRIGGER",
                            2: "AREA_REACTION_TRIGGER",
                        },
                        "params": {
                            "reactToVoxelDestruction": True,
                            "triggerName": "Auto",
                        },
                        "pos": LuaVec3(8.0, 24.0, 40.0),
                        "rot": LuaQuat(0.0, 0.0, 0.0, 1.0),
                    }
                }
            }
        }
    }

    spawners = extract_spawners(value)

    assert len(spawners) == 1
    spawner = spawners[0]
    assert spawner.cell_x == -3
    assert spawner.cell_y == -6
    assert spawner.x == -3 * CELL_SIZE_METERS + 8.0
    assert spawner.y == -6 * CELL_SIZE_METERS + 24.0
    assert spawner.z == 40.0
    assert spawner.scale_x == 48.0
    assert spawner.tags == (
        "SPAWN_ENEMY_VOLUME_TRIGGER",
        "AREA_REACTION_TRIGGER",
    )
    assert spawner.trigger_name == "Auto"
    assert spawner.react_to_voxel_destruction is True
