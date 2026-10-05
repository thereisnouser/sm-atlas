from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import quote

SQLITE_HEADER = b"SQLite format 3\x00"

KNOWN_SCRAP_MECHANIC_TABLES = {
    "GenericData",
    "ScriptData",
    "RigidBody",
    "ChildShape",
    "Harvestable",
    "Unit",
}


class InvalidSaveFile(ValueError):
    """Raised when a file is not a valid SQLite save database."""


class SaveDatabase:
    """Read-only access to a Scrap Mechanic save database."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    def validate(self) -> None:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)

        with self.path.open("rb") as file:
            header = file.read(len(SQLITE_HEADER))

        if header != SQLITE_HEADER:
            raise InvalidSaveFile(f"{self.path} is not a SQLite database")

    def connect(self) -> sqlite3.Connection:
        self.validate()
        uri_path = quote(self.path.as_posix(), safe="/:")
        connection = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def tables(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()

        return [row["name"] for row in rows]

    def row_count(self, table: str) -> int:
        if table not in self.tables():
            raise KeyError(f"Unknown table: {table}")

        escaped_table = table.replace('"', '""')
        with self.connect() as connection:
            row = connection.execute(
                f'SELECT COUNT(*) AS count FROM "{escaped_table}"'
            ).fetchone()

        return int(row["count"])

    def inspect(self) -> dict[str, object]:
        tables = self.tables()
        counts = {table: self.row_count(table) for table in tables}
        detected = sorted(KNOWN_SCRAP_MECHANIC_TABLES.intersection(tables))

        return {
            "path": str(self.path),
            "tables": counts,
            "known_tables": detected,
            "sm_signal": f"{len(detected)}/{len(KNOWN_SCRAP_MECHANIC_TABLES)}",
        }
