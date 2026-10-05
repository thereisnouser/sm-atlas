from __future__ import annotations

import os
from pathlib import Path

from sm_atlas.discovery import default_user_root, find_survival_saves


def test_find_survival_saves(tmp_path: Path) -> None:
    old_save = tmp_path / "User_1" / "Save" / "Survival" / "old.db"
    new_save = tmp_path / "User_2" / "Save" / "Survival" / "new.db"

    old_save.parent.mkdir(parents=True)
    new_save.parent.mkdir(parents=True)

    old_save.write_bytes(b"old")
    new_save.write_bytes(b"new")

    os.utime(old_save, (1_000, 1_000))
    os.utime(new_save, (2_000, 2_000))

    saves = find_survival_saves(tmp_path)

    assert [save.path.name for save in saves] == ["new.db", "old.db"]


def test_find_survival_saves_returns_empty_for_missing_root(
    tmp_path: Path,
) -> None:
    assert find_survival_saves(tmp_path / "missing") == []


def test_default_user_root_uses_appdata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))

    assert default_user_root() == (
        tmp_path
        / "Axolot Games"
        / "Scrap Mechanic"
        / "User"
    )
