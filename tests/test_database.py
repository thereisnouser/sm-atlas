from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sm_atlas.database import InvalidSaveFile, SaveDatabase


def create_test_save(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE GenericData (id INTEGER PRIMARY KEY, value BLOB)")
    connection.execute("CREATE TABLE ScriptData (id INTEGER PRIMARY KEY, value BLOB)")
    connection.execute("CREATE TABLE CustomTable (id INTEGER PRIMARY KEY)")
    connection.executemany(
        "INSERT INTO CustomTable (id) VALUES (?)",
        [(1,), (2,), (3,)],
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


def test_invalid_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "not-a-save.db"
    path.write_text("not sqlite", encoding="utf-8")

    with pytest.raises(InvalidSaveFile):
        SaveDatabase(path).inspect()
