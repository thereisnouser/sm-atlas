from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from struct import unpack_from
from typing import Any

from .database import SaveDatabase
from .formats.generic_data import (
    WORLD_MARKER_UID,
    GenericDataError,
    decode_envelope,
)


class WorldDataError(ValueError):
    """Raised when a world definition cannot be decoded."""


@dataclass(frozen=True)
class WorldInfo:
    world_id: int
    seed: int
    filename: str
    classname: str
    terrain_params: str

    @property
    def terrain(self) -> Any:
        try:
            return json.loads(self.terrain_params)
        except (json.JSONDecodeError, TypeError):
            return self.terrain_params

    @property
    def kind(self) -> str:
        if self.classname == "Overworld":
            return "overworld"
        if self.classname == "DungeonWorld":
            return "dungeon"
        if self.classname == "WarehouseWorld":
            return "warehouse"
        if self.classname.startswith("UndergroundWorld"):
            return "underground"

        return "other"

    @property
    def depth(self) -> int | None:
        terrain = self.terrain
        if not isinstance(terrain, dict):
            return None

        value = terrain.get("depth")
        if isinstance(value, (int, float)):
            return int(value)

        return None

    @property
    def label(self) -> str:
        terrain = self.terrain

        if self.kind == "warehouse" and isinstance(terrain, dict):
            index = terrain.get("warehouseIndex")
            level = terrain.get("level")
            max_levels = terrain.get("maxLevels")
            quest = terrain.get("isQuestWarehouse") is True

            if (
                isinstance(index, (int, float))
                and isinstance(level, (int, float))
            ):
                prefix = "Quest Warehouse" if quest else "Warehouse"
                label = f"{prefix} {int(index)} L{int(level)}"
                if isinstance(max_levels, (int, float)):
                    label += f"/{int(max_levels)}"
                return label

        if isinstance(terrain, dict):
            path = terrain.get("path") or terrain.get("worldFilePath")
            if isinstance(path, str) and path:
                name = PurePosixPath(path.replace("\\", "/")).stem
                if name:
                    if self.kind == "underground" and self.depth is not None:
                        return f"D{self.depth} {name}"
                    return name

        return self.classname or f"World {self.world_id}"

    def to_dict(self) -> dict[str, object]:
        return {
            "world_id": self.world_id,
            "label": self.label,
            "kind": self.kind,
            "depth": self.depth,
            "seed": self.seed,
            "filename": self.filename,
            "classname": self.classname,
            "terrain_params": self.terrain,
        }


def _read_string(data: bytes, offset: int) -> tuple[str, int]:
    if offset + 2 > len(data):
        raise WorldDataError("truncated string length")

    length = unpack_from(">H", data, offset)[0]
    offset += 2
    end = offset + length

    if end > len(data):
        raise WorldDataError("truncated string data")

    try:
        value = data[offset:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorldDataError("invalid UTF-8 in world data") from exc

    return value, end


def decode_world_payload(data: bytes) -> tuple[int, str, str, str]:
    if len(data) < 4:
        raise WorldDataError("world payload is too short")

    seed = unpack_from(">I", data, 0)[0]
    offset = 4

    filename, offset = _read_string(data, offset)
    classname, offset = _read_string(data, offset)
    terrain_params, _ = _read_string(data, offset)

    return seed, filename, classname, terrain_params


def discover_worlds(database: SaveDatabase) -> list[WorldInfo]:
    with database.connect() as connection:
        if "GenericData" not in database._tables(connection):
            return []

        rows = connection.execute(
            """
            SELECT worldId, data
            FROM GenericData
            WHERE uid = ?
              AND flags = 3
            ORDER BY worldId
            """,
            (WORLD_MARKER_UID,),
        ).fetchall()

    worlds: list[WorldInfo] = []

    for row in rows:
        blob = row["data"]
        if not isinstance(blob, bytes):
            continue

        try:
            envelope = decode_envelope(blob)
            seed, filename, classname, terrain_params = (
                decode_world_payload(envelope.data)
            )
        except (GenericDataError, WorldDataError):
            continue

        sql_world_id = int(row["worldId"])
        if envelope.world_id != sql_world_id:
            raise WorldDataError(
                "worldId mismatch between GenericData row and envelope"
            )

        worlds.append(
            WorldInfo(
                world_id=sql_world_id,
                seed=seed,
                filename=filename,
                classname=classname,
                terrain_params=terrain_params,
            )
        )

    return worlds
