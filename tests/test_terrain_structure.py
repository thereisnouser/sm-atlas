from __future__ import annotations

import sqlite3
from pathlib import Path
from struct import pack

from sm_atlas.database import SaveDatabase
from sm_atlas.terrain_structure import (
    analyze_structure_record,
    probe_voxel_terrain_structure,
)


def make_blob(
    record_id: int,
    chunk_x: int,
    chunk_y: int,
    chunk_z: int,
    *,
    prefix: bytes = b"\xc0",
) -> bytes:
    return b"".join(
        [
            prefix,
            b"\x0c\x00\x01",
            pack(">I", record_id),
            b"\xff\xff\xff\xff",
            b"\x00\x01\x00\xff",
            b"\x05\x17\x00\x17",
            pack(">iii", chunk_x, chunk_y, chunk_z),
            b"payload",
        ]
    )


def test_structure_record_detects_marker_id_and_coordinates() -> None:
    record = analyze_structure_record(
        record_id=2027,
        cell_x=0,
        cell_y=-1,
        blob=make_blob(2027, 3, -2, 1),
    )

    assert record.marker_offset == 1
    assert record.id_offset == 4
    assert record.prefix_hex == "c0"
    assert record.has_minus_one_sentinel is True
    assert record.candidate is not None
    assert record.candidate.x == 3
    assert record.candidate.y == -2
    assert record.candidate.z == 1
    assert record.candidate.exact_cell_match is True


def test_structure_probe_aggregates_variants(tmp_path: Path) -> None:
    save_path = tmp_path / "save.db"
    connection = sqlite3.connect(save_path)
    connection.execute(
        """
        CREATE TABLE VoxelTerrain (
            id INTEGER PRIMARY KEY,
            worldId INTEGER,
            x INTEGER,
            y INTEGER,
            data BLOB
        )
        """
    )
    connection.executemany(
        """
        INSERT INTO VoxelTerrain (id, worldId, x, y, data)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (2027, 23, 0, -1, make_blob(2027, 3, -2, 1)),
            (
                2028,
                23,
                1,
                -1,
                make_blob(
                    2028,
                    4,
                    -3,
                    2,
                    prefix=b"\xf0\x0c",
                ),
            ),
        ],
    )
    connection.commit()
    connection.close()

    result = probe_voxel_terrain_structure(
        SaveDatabase(save_path),
        world_id=23,
        limit=10,
        examples=10,
    )

    assert result["scanned_records"] == 2
    assert result["marker_matches"] == 2
    assert result["id_matches"] == 2
    assert result["sentinel_matches"] == 2
    assert result["direct_coordinate_candidates"] == 2
    assert result["exact_cell_matches"] == 2
    assert result["marker_offsets"] == {"1": 1, "2": 1}
    assert result["id_offsets"] == {"4": 1, "5": 1}
    assert result["candidate_z_range"] == {"min": 1, "max": 2}
