from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .formats.lua_values import LuaQuat, LuaUuid, LuaVec3

CHUNK_SIZE_METERS = 16.0
CHUNKS_PER_CELL = 4
CELL_SIZE_METERS = CHUNK_SIZE_METERS * CHUNKS_PER_CELL


@dataclass(frozen=True)
class UndergroundPiece:
    kind: str
    cell_x: int
    cell_y: int
    tile_index: int
    tile_uuid: str | None
    x: float
    y: float
    z: float
    width: float
    depth: float
    height: float
    rotation: int
    source_x: int
    source_y: int

    @property
    def max_x(self) -> float:
        return self.x + self.width

    @property
    def max_y(self) -> float:
        return self.y + self.depth

    @property
    def max_z(self) -> float:
        return self.z + self.height

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "cell_x": self.cell_x,
            "cell_y": self.cell_y,
            "tile_index": self.tile_index,
            "tile_uuid": self.tile_uuid,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "width": self.width,
            "depth": self.depth,
            "height": self.height,
            "rotation": self.rotation,
            "source_x": self.source_x,
            "source_y": self.source_y,
        }


@dataclass(frozen=True)
class UndergroundSpawner:
    cell_x: int
    cell_y: int
    x: float
    y: float
    z: float
    scale_x: float
    scale_y: float
    scale_z: float
    tags: tuple[str, ...]
    trigger_name: str | None
    react_to_voxel_destruction: bool | None

    def to_dict(self) -> dict[str, object]:
        return {
            "cell_x": self.cell_x,
            "cell_y": self.cell_y,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "scale_z": self.scale_z,
            "tags": list(self.tags),
            "trigger_name": self.trigger_name,
            "react_to_voxel_destruction": self.react_to_voxel_destruction,
        }


def _tile_lookup(value: dict[Any, Any]) -> dict[int, str]:
    raw_tiles = value.get("tileList")
    if not isinstance(raw_tiles, dict):
        return {}

    result: dict[int, str] = {}

    for index, raw_uuid in raw_tiles.items():
        if isinstance(index, int) and isinstance(raw_uuid, LuaUuid):
            result[index] = str(raw_uuid)

    return result


def _decode_cave(
    raw_value: int,
    *,
    cell_x: int,
    cell_y: int,
    tile_lookup: dict[int, str],
) -> UndergroundPiece:
    value = raw_value & 0xFFFFFFFF

    tile_index = value & 0xFF
    z_chunk = (value >> 8) & 0x0F
    height_chunks = ((value >> 12) & 0x0F) + 1
    source_cell_x = (value >> 16) & 0x03
    source_cell_y = (value >> 18) & 0x03
    rotation = (value >> 20) & 0x03

    return UndergroundPiece(
        kind="cave",
        cell_x=cell_x,
        cell_y=cell_y,
        tile_index=tile_index,
        tile_uuid=tile_lookup.get(tile_index),
        x=cell_x * CELL_SIZE_METERS,
        y=cell_y * CELL_SIZE_METERS,
        z=z_chunk * CHUNK_SIZE_METERS,
        width=CELL_SIZE_METERS,
        depth=CELL_SIZE_METERS,
        height=height_chunks * CHUNK_SIZE_METERS,
        rotation=rotation,
        source_x=source_cell_x * CHUNKS_PER_CELL,
        source_y=source_cell_y * CHUNKS_PER_CELL,
    )


def _decode_pocket(
    raw_value: int,
    *,
    cell_x: int,
    cell_y: int,
    tile_lookup: dict[int, str],
) -> UndergroundPiece:
    value = raw_value & 0xFFFFFFFF

    tile_index = value & 0xFF

    placement = (value >> 8) & 0xFF
    local_x = placement & 0x03
    local_y = (placement >> 2) & 0x03
    z_chunk = (placement >> 4) & 0x0F

    packed_size = (value >> 16) & 0xFF
    width_chunks = (packed_size & 0x03) + 1
    depth_chunks = ((packed_size >> 2) & 0x03) + 1
    height_chunks = ((packed_size >> 4) & 0x0F) + 1

    source_x = (value >> 24) & 0x03
    source_y = (value >> 26) & 0x03
    rotation = (value >> 28) & 0x03

    if rotation & 1:
        world_width_chunks = depth_chunks
        world_depth_chunks = width_chunks
    else:
        world_width_chunks = width_chunks
        world_depth_chunks = depth_chunks

    return UndergroundPiece(
        kind="pocket",
        cell_x=cell_x,
        cell_y=cell_y,
        tile_index=tile_index,
        tile_uuid=tile_lookup.get(tile_index),
        x=(
            cell_x * CELL_SIZE_METERS
            + local_x * CHUNK_SIZE_METERS
        ),
        y=(
            cell_y * CELL_SIZE_METERS
            + local_y * CHUNK_SIZE_METERS
        ),
        z=z_chunk * CHUNK_SIZE_METERS,
        width=world_width_chunks * CHUNK_SIZE_METERS,
        depth=world_depth_chunks * CHUNK_SIZE_METERS,
        height=height_chunks * CHUNK_SIZE_METERS,
        rotation=rotation,
        source_x=source_x,
        source_y=source_y,
    )


def _extract_grid_pieces(
    value: dict[Any, Any],
    *,
    field: str,
    decoder,
) -> list[UndergroundPiece]:
    raw_grid = value.get(field)
    if not isinstance(raw_grid, dict):
        return []

    tile_lookup = _tile_lookup(value)
    pieces: list[UndergroundPiece] = []

    for cell_y, raw_row in raw_grid.items():
        if not isinstance(cell_y, int) or not isinstance(raw_row, dict):
            continue

        for cell_x, raw_entries in raw_row.items():
            if not isinstance(cell_x, int) or not isinstance(raw_entries, dict):
                continue

            for raw_value in raw_entries.values():
                if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                    continue

                pieces.append(
                    decoder(
                        raw_value,
                        cell_x=cell_x,
                        cell_y=cell_y,
                        tile_lookup=tile_lookup,
                    )
                )

    return pieces


def extract_caves(value: dict[Any, Any]) -> list[UndergroundPiece]:
    return _extract_grid_pieces(
        value,
        field="caves",
        decoder=_decode_cave,
    )


def extract_pockets(value: dict[Any, Any]) -> list[UndergroundPiece]:
    return _extract_grid_pieces(
        value,
        field="pockets",
        decoder=_decode_pocket,
    )


def summarize_pieces(
    pieces: list[UndergroundPiece],
) -> dict[str, object]:
    if not pieces:
        return {
            "count": 0,
            "tile_indices": {},
            "bounds": None,
        }

    tile_counts: dict[int, int] = {}
    for piece in pieces:
        tile_counts[piece.tile_index] = tile_counts.get(piece.tile_index, 0) + 1

    return {
        "count": len(pieces),
        "tile_indices": dict(
            sorted(
                tile_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "bounds": {
            "min_x": min(piece.x for piece in pieces),
            "max_x": max(piece.max_x for piece in pieces),
            "min_y": min(piece.y for piece in pieces),
            "max_y": max(piece.max_y for piece in pieces),
            "min_z": min(piece.z for piece in pieces),
            "max_z": max(piece.max_z for piece in pieces),
        },
    }


def extract_spawners(value: dict[Any, Any]) -> list[UndergroundSpawner]:
    raw_grid = value.get("spawners")
    if not isinstance(raw_grid, dict):
        return []

    spawners: list[UndergroundSpawner] = []

    for cell_y, raw_row in raw_grid.items():
        if not isinstance(cell_y, int) or not isinstance(raw_row, dict):
            continue

        for cell_x, raw_entries in raw_row.items():
            if not isinstance(cell_x, int) or not isinstance(raw_entries, dict):
                continue

            for raw_spawner in raw_entries.values():
                if not isinstance(raw_spawner, dict):
                    continue

                pos = raw_spawner.get("pos")
                scale = raw_spawner.get("scale")

                if not isinstance(pos, LuaVec3):
                    continue
                if not isinstance(scale, LuaVec3):
                    continue

                raw_tags = raw_spawner.get("tags")
                tags: list[tuple[int, str]] = []
                if isinstance(raw_tags, dict):
                    for index, tag in raw_tags.items():
                        if isinstance(index, int) and isinstance(tag, str):
                            tags.append((index, tag))
                tags.sort(key=lambda item: item[0])

                raw_params = raw_spawner.get("params")
                trigger_name = None
                react_to_voxel_destruction = None
                if isinstance(raw_params, dict):
                    raw_trigger_name = raw_params.get("triggerName")
                    if isinstance(raw_trigger_name, str):
                        trigger_name = raw_trigger_name

                    raw_react = raw_params.get("reactToVoxelDestruction")
                    if isinstance(raw_react, bool):
                        react_to_voxel_destruction = raw_react

                spawners.append(
                    UndergroundSpawner(
                        cell_x=cell_x,
                        cell_y=cell_y,
                        x=cell_x * CELL_SIZE_METERS + float(pos.x),
                        y=cell_y * CELL_SIZE_METERS + float(pos.y),
                        z=float(pos.z),
                        scale_x=float(scale.x),
                        scale_y=float(scale.y),
                        scale_z=float(scale.z),
                        tags=tuple(tag for _, tag in tags),
                        trigger_name=trigger_name,
                        react_to_voxel_destruction=react_to_voxel_destruction,
                    )
                )

    return spawners


def summarize_spawners(
    spawners: list[UndergroundSpawner],
) -> dict[str, object]:
    if not spawners:
        return {
            "count": 0,
            "tags": {},
            "trigger_names": {},
            "bounds": None,
        }

    tag_counts: dict[str, int] = {}
    trigger_counts: dict[str, int] = {}

    for spawner in spawners:
        for tag in spawner.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

        if spawner.trigger_name is not None:
            trigger_counts[spawner.trigger_name] = (
                trigger_counts.get(spawner.trigger_name, 0) + 1
            )

    return {
        "count": len(spawners),
        "tags": dict(
            sorted(
                tag_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "trigger_names": dict(
            sorted(
                trigger_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "bounds": {
            "min_x": min(spawner.x for spawner in spawners),
            "max_x": max(spawner.x for spawner in spawners),
            "min_y": min(spawner.y for spawner in spawners),
            "max_y": max(spawner.y for spawner in spawners),
            "min_z": min(spawner.z for spawner in spawners),
            "max_z": max(spawner.z for spawner in spawners),
        },
    }
