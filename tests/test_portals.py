from __future__ import annotations

import sqlite3
import struct
from pathlib import Path

import pytest

from sm_atlas.database import SaveDatabase
from sm_atlas.portals import (
    _common_prefix_length,
    _common_suffix_length,
    _decoded_matches_columns,
    _decode_portal_blob_header,
    _header_matches_columns,
    _position_to_cell,
    _opening_a_position_candidate,
    _scan_aligned_be_floats,
    decode_portal_blob,
    discover_portals,
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
            struct.pack(">f", 0.0),
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


def test_opening_a_position_candidate_decodes_first_vec3() -> None:
    assert _opening_a_position_candidate(portal_blob()) == (
        21.0,
        -3.5,
        0.0,
    )


def test_common_prefix_and_suffix_lengths() -> None:
    values = [
        bytes.fromhex("aabbcc001122"),
        bytes.fromhex("aabbddff1122"),
        bytes.fromhex("aabbeeff1122"),
    ]

    assert _common_prefix_length(values) == 2
    assert _common_suffix_length(values) == 2


REAL_PORTAL_BLOB = bytes.fromhex(
    "09000100000043ff00000002fffffffe000cff00000000000000000017"
    "41a8084e41c8000041000000800330b001a610c74c1710a28b04c000"
    "0000000000000fdfffffc00000002001741ffe598421cc17242942c14"
    "00000000000000003f7fffff333bbd2fc000000000000000000000000"
    "000000000000000000000000"
)


PARTIAL_PORTAL_BLOB = bytes.fromhex(
    "09000100000003ff00000000ffffffd70001ff0000000000000000ffff"
    "3fd9999a3fd9999a403ccccd800071482d8010944000100000000fc00"
    "0000fc000000fc000000fc0000018000000000000000000000000000"
    "000000000000000000000"
)


def test_decode_portal_blob_extracts_bit_packed_transforms() -> None:
    decoded = decode_portal_blob(REAL_PORTAL_BLOB)

    assert decoded is not None
    assert decoded.dimensions == pytest.approx(
        (21.004055, 25.0, 8.0),
        rel=1e-6,
    )

    assert decoded.side_a_prefix == 2
    assert decoded.world_id_a == 12
    assert decoded.position_a == pytest.approx(
        (-96.012878, 157.188904, 69.086082),
        rel=1e-6,
    )
    assert decoded.rotation_a == pytest.approx(
        (0.0, 0.0, 0.99999994, 0.0),
        abs=1e-7,
    )

    assert decoded.side_b_prefix == 2
    assert decoded.world_id_b == 23
    assert decoded.position_b == pytest.approx(
        (31.987106, 39.188911, 74.08609),
        rel=1e-6,
    )
    assert decoded.rotation_b == pytest.approx(
        (0.0, 0.0, 0.99999994, 4.371139e-08),
        abs=1e-7,
    )

    assert decoded.tail_bit_offset == 812
    assert len(decoded.tail_bits) == 196
    assert decoded.tail_bits == "11" + "0" * 194


def test_decoded_portal_positions_reproduce_database_cells() -> None:
    decoded = decode_portal_blob(REAL_PORTAL_BLOB)

    assert decoded is not None
    assert _position_to_cell(decoded.position_a) == (-2, 2)
    assert _position_to_cell(decoded.position_b) == (0, 0)
    assert _decoded_matches_columns(
        decoded,
        world_id_a=12,
        x_a=-2,
        y_a=2,
        world_id_b=23,
        x_b=0,
        y_b=0,
    )


def test_decode_portal_blob_returns_none_for_short_payload() -> None:
    assert decode_portal_blob(portal_blob()) is None


def test_decode_partial_portal_blob_keeps_side_a_transform() -> None:
    decoded = decode_portal_blob(PARTIAL_PORTAL_BLOB)

    assert decoded is not None
    assert decoded.position_a == pytest.approx(
        (-2571.375, 52.25, 2.0),
        rel=1e-6,
    )
    assert decoded.rotation_a == pytest.approx(
        (0.5, 0.5, 0.5, 0.5),
        abs=1e-7,
    )
    assert decoded.position_b is None
    assert decoded.rotation_b is None
    assert decoded.world_id_b is None
    assert decoded.tail_bit_offset == 570
    assert len(decoded.tail_bits) == 198
    assert _decoded_matches_columns(
        decoded,
        world_id_a=1,
        x_a=-41,
        y_a=0,
        world_id_b=65535,
        x_b=0,
        y_b=0,
    )



def test_discover_portals_exposes_validated_transforms(
    tmp_path: Path,
) -> None:
    save_path = tmp_path / "save.db"
    connection = sqlite3.connect(save_path)
    connection.execute(
        """
        CREATE TABLE Portal (
            id INTEGER PRIMARY KEY,
            worldIdA INTEGER,
            xA INTEGER,
            yA INTEGER,
            worldIdB INTEGER,
            xB INTEGER,
            yB INTEGER,
            data BLOB
        )
        """
    )
    connection.executemany(
        """
        INSERT INTO Portal (
            id, worldIdA, xA, yA, worldIdB, xB, yB, data
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                67,
                12,
                -2,
                2,
                23,
                0,
                0,
                REAL_PORTAL_BLOB,
            ),
            (
                3,
                1,
                -41,
                0,
                65535,
                0,
                0,
                PARTIAL_PORTAL_BLOB,
            ),
        ],
    )
    connection.commit()
    connection.close()

    portals = {
        portal.portal_id: portal
        for portal in discover_portals(SaveDatabase(save_path))
    }

    assert portals[67].decoded is not None
    assert portals[67].decoded.position_b == pytest.approx(
        (31.987106, 39.188911, 74.08609),
        rel=1e-6,
    )
    assert portals[3].decoded is not None
    assert portals[3].decoded.position_a == pytest.approx(
        (-2571.375, 52.25, 2.0),
        rel=1e-6,
    )
    assert portals[3].decoded.position_b is None
