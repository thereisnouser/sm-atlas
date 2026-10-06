from __future__ import annotations

from sm_atlas.formats.lua_values import LuaVec3
from sm_atlas.terrain_data_structure import _profile_value


def test_profile_value_reports_nested_signatures() -> None:
    value = {
        1: {
            "positions": {
                1: LuaVec3(1.0, 2.0, 3.0),
                2: LuaVec3(4.0, 5.0, 6.0),
            },
            "tunnelType": "TtDefault",
        },
        2: {
            "positions": {
                1: LuaVec3(7.0, 8.0, 9.0),
            },
            "tunnelType": "TtVeinRich",
        },
    }

    profile = _profile_value(
        value,
        examples=2,
        depth=4,
        max_items=8,
    )

    assert profile["type"] == "table"
    assert profile["items"] == 2
    assert profile["key_types"] == {"int": 2}
    assert profile["value_types"] == {"table": 2}
    assert profile["nested_signatures"] == {
        "positions, tunnelType": 2
    }
    assert (
        profile["examples"][0]["value"]["positions"]["1"]["type"]
        == "vec3"
    )
