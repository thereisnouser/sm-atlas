from __future__ import annotations

from sm_atlas.formats.lua_values import LuaVec3
from sm_atlas.underground_tunnels import _extract_tunnels


def test_extract_tunnels_reads_points_and_length() -> None:
    value = {
        "tunnels": {
            1: {
                "tunnelType": "TtVeinT4",
                "positions": {
                    1: LuaVec3(0.0, 0.0, 0.0),
                    2: LuaVec3(3.0, 4.0, 0.0),
                    3: LuaVec3(3.0, 4.0, 12.0),
                },
            }
        }
    }

    tunnels = _extract_tunnels(value)

    assert len(tunnels) == 1
    assert tunnels[0]["id"] == 1
    assert tunnels[0]["type"] == "TtVeinT4"
    assert tunnels[0]["length"] == 17.0
    assert tunnels[0]["points"] == [
        (0.0, 0.0, 0.0),
        (3.0, 4.0, 0.0),
        (3.0, 4.0, 12.0),
    ]
