from __future__ import annotations

import struct

from sm_atlas.portals import (
    _decode_portal_blob_header,
    _header_matches_columns,
    _scan_aligned_be_floats,
)


def portal_blob() -> bytes:
    return b"".join(
        (
            bytes([9]),
            (1).to_bytes(2, "big"),
            (67).to_bytes(4, "big"),
            bytes([255]),
            (2).to_bytes(4, "big", signed=True),
            (-2).to_bytes(4, "big", signed=True),
            (12).to_bytes(2, "big"),
            bytes([255]),
            (0).to_bytes(4, "big", signed=True),
            (0).to_bytes(4, "big", signed=True),
            (23).to_bytes(2, "big"),
            struct.pack(">f", 21.0),
            struct.pack(">f", -3.5),
        )
    )


def test_decode_portal_blob_header_matches_database_columns() -> None:
    data = portal_blob()
    header = _decode_portal_blob_header(data)

    assert header is not None
    assert header["id"] == 67
    assert header["world_id_a"] == 12
    assert header["x_a"] == -2
    assert header["y_a"] == 2
    assert header["world_id_b"] == 23
    assert header["x_b"] == 0
    assert header["y_b"] == 0

    assert _header_matches_columns(
        header,
        portal_id=67,
        world_id_a=12,
        x_a=-2,
        y_a=2,
        world_id_b=23,
        x_b=0,
        y_b=0,
    )


def test_scan_portal_floats_after_fixed_header() -> None:
    values = _scan_aligned_be_floats(portal_blob())

    assert values[0]["offset"] == 29
    assert values[0]["value"] == 21.0
    assert values[1]["offset"] == 33
    assert values[1]["value"] == -3.5
