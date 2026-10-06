from __future__ import annotations

from sm_atlas.underground_tile_catalog import (
    _name_tags,
    _tile_family,
    _tile_name,
)


def test_tile_catalog_classifies_standard_underground_paths() -> None:
    cave = (
        "$SURVIVAL_DATA/Terrain/Tiles/underground/Drill2/"
        "Cave/drill2_cave_5b_bot_8x8x5.tile"
    )
    passage = (
        "$SURVIVAL_DATA/Terrain/Tiles/underground/Drill2/"
        "Tunnelpocket/Small/"
        "drill2_tunnelpocket_small_passage_01_2x2x2.tile"
    )
    elevator = (
        "$SURVIVAL_DATA/Terrain/Tiles/underground/Drill2/"
        "drill2_elevator_12x8x8.tile"
    )

    assert _tile_name(cave) == "drill2_cave_5b_bot_8x8x5.tile"
    assert _tile_family(cave) == "cave"
    assert _tile_family(passage) == "tunnel_pocket"
    assert _name_tags(passage) == ("passage",)
    assert _tile_family(elevator) == "elevator"
    assert "elevator" in _name_tags(elevator)
