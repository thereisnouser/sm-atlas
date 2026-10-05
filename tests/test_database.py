from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sm_atlas.database import InvalidSaveFile, SaveDatabase


def create_test_save(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE GenericData (id INTEGER PRIMARY KEY, value BLOB)"
    )
    connection.execute(
        "CREATE TABLE ScriptData (id INTEGER PRIMARY KEY, value BLOB)"
    )
    connection.execute(
        "CREATE TABLE CustomTable ("
        "id INTEGER PRIMARY KEY, "
        "name TEXT, "
        "payload BLOB"
        ")"
    )
    connection.executemany(
        "INSERT INTO CustomTable (id, name, payload) VALUES (?, ?, ?)",
        [
            (1, "alpha", b"\x01\x02\x03"),
            (2, "beta", b"\xff\x00"),
            (3, "gamma", b""),
        ],
    )
    connection.commit()
    connection.close()


def test_inspect_reads_tables_without_modifying_database(tmp_path: Path) -> None:
    save_path = tmp_path / "save.db"
    create_test_save(save_path)

    result = SaveDatabase(save_path).inspect()

    assert result["tables"]["CustomTable"] == 3
    assert result["tables"]["GenericData"] == 0
    assert result["known_tables"] == ["GenericData", "ScriptData"]
    assert result["sm_signal"] == "2/6"


def test_schema_returns_columns(tmp_path: Path) -> None:
    save_path = tmp_path / "save.db"
    create_test_save(save_path)

    schema = SaveDatabase(save_path).schema("CustomTable")

    assert [column["name"] for column in schema] == [
        "id",
        "name",
        "payload",
    ]
    assert schema[0]["pk"] is True
    assert schema[2]["type"] == "BLOB"


def test_sample_previews_blobs(tmp_path: Path) -> None:
    save_path = tmp_path / "save.db"
    create_test_save(save_path)

    rows = SaveDatabase(save_path).sample("CustomTable", limit=1)

    assert rows == [
        {
            "id": 1,
            "name": "alpha",
            "payload": {
                "type": "blob",
                "size": 3,
                "hex_prefix": "010203",
            },
        }
    ]


def test_sample_rejects_invalid_limit(tmp_path: Path) -> None:
    save_path = tmp_path / "save.db"
    create_test_save(save_path)

    with pytest.raises(ValueError):
        SaveDatabase(save_path).sample("CustomTable", limit=0)


def test_invalid_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "not-a-save.db"
    path.write_text("not sqlite", encoding="utf-8")

    with pytest.raises(InvalidSaveFile):
        SaveDatabase(path).inspect()
