from __future__ import annotations

from dataclasses import dataclass

from .database import SaveDatabase
from .worlds import WorldInfo, discover_worlds


@dataclass(frozen=True)
class TerrainSummary:
    world_id: int
    label: str
    kind: str
    depth: int | None
    records: int
    unique_coordinates: int
    min_x: int
    max_x: int
    min_y: int
    max_y: int
    total_blob_bytes: int
    min_blob_bytes: int
    max_blob_bytes: int

    @property
    def records_per_coordinate(self) -> float:
        if self.unique_coordinates == 0:
            return 0.0
        return self.records / self.unique_coordinates

    def to_dict(self) -> dict[str, object]:
        return {
            "world_id": self.world_id,
            "label": self.label,
            "kind": self.kind,
            "depth": self.depth,
            "records": self.records,
            "unique_coordinates": self.unique_coordinates,
            "records_per_coordinate": round(
                self.records_per_coordinate,
                3,
            ),
            "bounds": {
                "min_x": self.min_x,
                "max_x": self.max_x,
                "min_y": self.min_y,
                "max_y": self.max_y,
            },
            "blob_bytes": {
                "total": self.total_blob_bytes,
                "min": self.min_blob_bytes,
                "max": self.max_blob_bytes,
            },
        }


def summarize_voxel_terrain(
    database: SaveDatabase,
    *,
    underground_only: bool = False,
) -> list[TerrainSummary]:
    worlds = discover_worlds(database)
    world_map: dict[int, WorldInfo] = {
        world.world_id: world
        for world in worlds
    }

    with database.connect() as connection:
        if "VoxelTerrain" not in database._tables(connection):
            return []

        rows = connection.execute(
            """
            WITH coordinate_counts AS (
                SELECT worldId, COUNT(*) AS unique_coordinates
                FROM (
                    SELECT DISTINCT worldId, x, y
                    FROM VoxelTerrain
                )
                GROUP BY worldId
            ),
            record_stats AS (
                SELECT
                    worldId,
                    COUNT(*) AS records,
                    MIN(x) AS min_x,
                    MAX(x) AS max_x,
                    MIN(y) AS min_y,
                    MAX(y) AS max_y,
                    COALESCE(SUM(length(data)), 0) AS total_blob_bytes,
                    COALESCE(MIN(length(data)), 0) AS min_blob_bytes,
                    COALESCE(MAX(length(data)), 0) AS max_blob_bytes
                FROM VoxelTerrain
                GROUP BY worldId
            )
            SELECT
                record_stats.*,
                coordinate_counts.unique_coordinates
            FROM record_stats
            JOIN coordinate_counts USING (worldId)
            ORDER BY worldId
            """
        ).fetchall()

    summaries: list[TerrainSummary] = []

    for row in rows:
        world_id = int(row["worldId"])
        world = world_map.get(world_id)

        kind = world.kind if world is not None else "unknown"
        if underground_only and kind != "underground":
            continue

        summaries.append(
            TerrainSummary(
                world_id=world_id,
                label=(
                    world.label
                    if world is not None
                    else f"World {world_id}"
                ),
                kind=kind,
                depth=world.depth if world is not None else None,
                records=int(row["records"]),
                unique_coordinates=int(row["unique_coordinates"]),
                min_x=int(row["min_x"]),
                max_x=int(row["max_x"]),
                min_y=int(row["min_y"]),
                max_y=int(row["max_y"]),
                total_blob_bytes=int(row["total_blob_bytes"]),
                min_blob_bytes=int(row["min_blob_bytes"]),
                max_blob_bytes=int(row["max_blob_bytes"]),
            )
        )

    return summaries
