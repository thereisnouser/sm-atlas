from __future__ import annotations

import sqlite3
from pathlib import Path
from struct import pack

from sm_atlas.database import SaveDatabase
from sm_atlas.formats.generic_data import WORLD_MARKER_UID
from sm_atlas.world_graph import build_world_graph


def literal_lz4_block(data: bytes) -> bytes:
    length = len(data)
    output = bytearray()

    if length < 15:
        output.append(length << 4)
    else:
        output.append(0xF0)
        remaining = length - 15
        while remaining >= 255:
            output.append(255)
            remaining -= 255
        output.append(remaining)

    output.extend(data)
    return bytes(output)


def make_world_payload(
    seed: int,
    filename: str,
    classname: str,
    terrain_params: str,
) -> bytes:
    output = bytearray(pack(">I", seed))

    for value in (filename, classname, terrain_params):
        encoded = value.encode("utf-8")
        output.extend(pack(">H", len(encoded)))
        output.extend(encoded)

    return bytes(output)


def make_world_envelope(world_id: int, payload: bytes) -> bytes:
    compressed = literal_lz4_block(payload)

    return b"".join(
        [
            WORLD_MARKER_UID,
            pack(">H", 4),
            pack("<I", world_id),
            pack(">H", world_id),
            pack("<I", 3),
            bytes([len(compressed)]),
            compressed,
        ]
    )


def insert_world(
    connection: sqlite3.Connection,
    world_id: int,
    classname: str,
    terrain_params: str,
) -> None:
    payload = make_world_payload(
        world_id * 100,
        "$SURVIVAL_DATA/Scripts/game/worlds/Test.lua",
        classname,
        terrain_params,
    )
    connection.execute(
        """
        INSERT INTO GenericData (uid, key, worldId, flags, data)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            WORLD_MARKER_UID,
            pack("<I", world_id),
            world_id,
            3,
            make_world_envelope(world_id, payload),
        ),
    )


def test_world_graph_can_filter_underground_connections(
    tmp_path: Path,
) -> None:
    save_path = tmp_path / "save.db"
    connection = sqlite3.connect(save_path)

    connection.execute(
        """
        CREATE TABLE GenericData (
            uid BLOB,
            key BLOB,
            worldId INTEGER,
            flags INTEGER,
            data BLOB
        )
        """
    )
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

    insert_world(connection, 1, "Overworld", "null")
    insert_world(
        connection,
        12,
        "UndergroundWorldMiningHub",
        '{"depth":1,"worldFilePath":"undergroundworld_mininghub.world"}',
    )
    insert_world(
        connection,
        13,
        "UndergroundWorldTutorial",
        '{"depth":2,"worldFilePath":"undergroundworld_onboarding.world"}',
    )

    connection.executemany(
        """
        INSERT INTO Portal (
            id, worldIdA, xA, yA, worldIdB, xB, yB, data
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, 1, 10, 20, 12, 0, 0, b""),
            (2, 12, 3, 4, 13, 5, 6, b""),
            (3, 1, 1, 2, 65535, 0, 0, b""),
        ],
    )
    connection.commit()
    connection.close()

    graph = build_world_graph(
        SaveDatabase(save_path),
        underground_only=True,
    )

    assert len(graph.worlds) == 3
    assert len(graph.connections) == 2
    assert graph.connections[0].a.kind == "overworld"
    assert graph.connections[0].b.kind == "underground"
    assert graph.connections[1].a.world_id == 12
    assert graph.connections[1].b.world_id == 13
