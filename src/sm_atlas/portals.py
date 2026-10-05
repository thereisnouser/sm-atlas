from __future__ import annotations

from dataclasses import dataclass

from .database import SaveDatabase


@dataclass(frozen=True)
class PortalInfo:
    portal_id: int
    world_id_a: int
    x_a: int
    y_a: int
    world_id_b: int
    x_b: int
    y_b: int

    def to_dict(self) -> dict[str, int]:
        return {
            "portal_id": self.portal_id,
            "world_id_a": self.world_id_a,
            "x_a": self.x_a,
            "y_a": self.y_a,
            "world_id_b": self.world_id_b,
            "x_b": self.x_b,
            "y_b": self.y_b,
        }


def discover_portals(database: SaveDatabase) -> list[PortalInfo]:
    with database.connect() as connection:
        if "Portal" not in database._tables(connection):
            return []

        rows = connection.execute(
            """
            SELECT id, worldIdA, xA, yA, worldIdB, xB, yB
            FROM Portal
            ORDER BY id
            """
        ).fetchall()

    return [
        PortalInfo(
            portal_id=int(row["id"]),
            world_id_a=int(row["worldIdA"]),
            x_a=int(row["xA"]),
            y_a=int(row["yA"]),
            world_id_b=int(row["worldIdB"]),
            x_b=int(row["xB"]),
            y_b=int(row["yB"]),
        )
        for row in rows
    ]
