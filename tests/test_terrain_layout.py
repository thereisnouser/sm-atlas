from __future__ import annotations

import sqlite3
from pathlib import Path
from struct import pack

from sm_atlas.database import SaveDatabase
from sm_atlas.terrain_layout import scan_voxel_terrain_layout


def make_blob(
    record_id: int,
    *,
    chunk_x: int,
    chunk_y: int,
    chunk_z: int,
    coordinate_relative_offset: int,
    prefix: bytes = b"\xc0",
) -> bytes:
    base = b"".join(
        [
            prefix,
            b"\x0c\x00\x01",
            pack(">I", record_id),
        ]
    )

    id_offset = len(prefix) + 3
    coordinate_offset = id_offset + coordinate_relative_offset

    padding_length = coordinate_offset - len(base)
    if padding_length < 0:
        raise ValueError("coordinate offset overlaps header")

    return b"".join(
        [
            base,
            b"\xaa" * padding_length,
            pack(">iii", chunk_x, chunk_y, chunk_z),
            b"payload",
        ]
    )


def test_layout_scan_finds_dominant_big_endian_factor4_offset(
    tmp_path: Path,
) -> None:
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

    rows = []
    for index in range(12):
        record_id = 2000 + index
        cell_x = index % 3
        cell_y = -1
        chunk_x = cell_x * 4 + (index % 4)
        chunk_y = cell_y * 4 + (index % 4)
        chunk_z = index % 8

        rows.append(
            (
                record_id,
                23,
                cell_x,
                cell_y,
                make_blob(
                    record_id,
                    chunk_x=chunk_x,
                    chunk_y=chunk_y,
                    chunk_z=chunk_z,
                    coordinate_relative_offset=20,
                    prefix=b"\xc0" if index % 2 == 0 else b"\xf0\x0c",
                ),
            )
        )

    connection.executemany(
        """
        INSERT INTO VoxelTerrain (id, worldId, x, y, data)
        VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )
    connection.commit()
    connection.close()

    result = scan_voxel_terrain_layout(
        SaveDatabase(save_path),
        world_id=23,
        limit=100,
        min_relative_offset=8,
        max_relative_offset=32,
        top=10,
    )

    best = result["top_layouts"][0]

    assert result["records_with_id"] == 12
    assert best["endian"] == "big"
    assert best["mapping"] == "direct"
    assert best["factor"] == 4
    assert best["relative_offset"] == 20
    assert best["exact_xy_matches"] == 12
    assert best["plausible_z_matches"] == 12


def test_layout_scan_reports_marker_offsets(tmp_path: Path) -> None:
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
            (
                1,
                23,
                0,
                0,
                make_blob(
                    1,
                    chunk_x=0,
                    chunk_y=0,
                    chunk_z=1,
                    coordinate_relative_offset=16,
                    prefix=b"\xc0",
                ),
            ),
            (
                2,
                23,
                0,
                0,
                make_blob(
                    2,
                    chunk_x=1,
                    chunk_y=1,
                    chunk_z=2,
                    coordinate_relative_offset=16,
                    prefix=b"\xf0\x0c",
                ),
            ),
        ],
    )
    connection.commit()
    connection.close()

    result = scan_voxel_terrain_layout(
        SaveDatabase(save_path),
        world_id=23,
        limit=10,
        min_relative_offset=8,
        max_relative_offset=24,
        top=5,
    )

    assert result["marker_offsets"] == {"1": 1, "2": 1}
