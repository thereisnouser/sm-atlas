from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCRAP_MECHANIC_USER_PATH = (
    Path("Axolot Games")
    / "Scrap Mechanic"
    / "User"
)


@dataclass(frozen=True)
class SaveInfo:
    path: Path
    size_bytes: int
    modified_at: datetime

    @classmethod
    def from_path(cls, path: Path) -> "SaveInfo":
        stat = path.stat()

        return cls(
            path=path.resolve(),
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(
                stat.st_mtime,
                tz=timezone.utc,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "name": self.path.stem,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at.isoformat(),
        }


def default_user_root() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None

    return Path(appdata) / SCRAP_MECHANIC_USER_PATH


def find_survival_saves(
    user_root: str | Path | None = None,
) -> list[SaveInfo]:
    if user_root is None:
        root = default_user_root()
        if root is None:
            return []
    else:
        root = Path(user_root).expanduser()

    if not root.is_dir():
        return []

    paths = [
        path
        for path in root.glob("*/Save/Survival/*.db")
        if path.is_file()
    ]

    saves = [SaveInfo.from_path(path) for path in paths]
    return sorted(
        saves,
        key=lambda save: (save.modified_at, save.path.name.lower()),
        reverse=True,
    )
