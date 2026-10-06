from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath
from typing import Any

from .database import SaveDatabase
from .formats.lua_values import LuaUuid
from .underground_features import extract_caves, extract_pockets
from .underground_tile_metadata import UNDERGROUND_TILE_METADATA
from .underground_tunnels import _load_terrain_table


def _tile_name(path: str) -> str:
    return PurePosixPath(path).name


def _tile_family(path: str) -> str:
    normalized = path.replace("\\", "/").lower()
    name = _tile_name(normalized)

    if "elevator" in name:
        return "elevator"
    if "/tunnelpocket/" in normalized:
        return "tunnel_pocket"
    if "/cave/" in normalized:
        return "cave"
    if "/pocket/" in normalized:
        return "pocket"
    if "/poi/" in normalized:
        return "poi"
    return "other"


def _name_tags(path: str) -> tuple[str, ...]:
    name = _tile_name(path).lower()
    tags: list[str] = []

    checks = (
        ("passage", "passage"),
        ("deposit", "deposit"),
        ("dungeon", "dungeon"),
        ("minerbot", "minerbot"),
        ("elevator", "elevator"),
        ("corralium", "corralium"),
        ("gold", "gold"),
        ("sapphire", "sapphire"),
        ("spark", "sparkstone"),
        ("potato", "potato"),
        ("crystal", "crystal"),
        ("cyrstal", "crystal"),
        ("formation", "formations"),
    )

    for needle, label in checks:
        if needle in name and label not in tags:
            tags.append(label)

    return tuple(tags)


def _tile_list(value: dict[Any, Any]) -> dict[int, str]:
    raw_tiles = value.get("tileList")
    if not isinstance(raw_tiles, dict):
        return {}

    result: dict[int, str] = {}

    for index, raw_uuid in raw_tiles.items():
        if isinstance(index, int) and isinstance(raw_uuid, LuaUuid):
            result[index] = str(raw_uuid)

    return result


def summarize_underground_tiles(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
    top: int = 30,
) -> dict[str, object]:
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    if not 1 <= top <= 200:
        raise ValueError("top must be between 1 and 200")

    row_id, value = _load_terrain_table(
        database,
        world_id=world_id,
        limit=limit,
    )

    tile_list = _tile_list(value)
    caves = extract_caves(value)
    pockets = extract_pockets(value)
    pieces = caves + pockets

    known_tile_list = {
        index: uuid
        for index, uuid in tile_list.items()
        if uuid in UNDERGROUND_TILE_METADATA
    }
    unknown_tile_list = {
        index: uuid
        for index, uuid in tile_list.items()
        if uuid not in UNDERGROUND_TILE_METADATA
    }

    usage: Counter[tuple[int, str, str]] = Counter()
    family_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    known_piece_count = 0

    for piece in pieces:
        uuid = piece.tile_uuid or ""
        usage[(piece.tile_index, uuid, piece.kind)] += 1

        meta = UNDERGROUND_TILE_METADATA.get(uuid)
        if meta is None:
            continue

        known_piece_count += 1
        path = str(meta["path"])
        family_counts[_tile_family(path)] += 1
        tag_counts.update(_name_tags(path))

    top_tiles = []
    for (tile_index, uuid, piece_kind), count in usage.most_common(top):
        meta = UNDERGROUND_TILE_METADATA.get(uuid)

        if meta is None:
            top_tiles.append(
                {
                    "tile_index": tile_index,
                    "uuid": uuid or None,
                    "piece_kind": piece_kind,
                    "placements": count,
                    "known": False,
                    "name": None,
                    "path": None,
                    "family": None,
                    "name_tags": [],
                    "catalog_size": None,
                }
            )
            continue

        path = str(meta["path"])
        top_tiles.append(
            {
                "tile_index": tile_index,
                "uuid": uuid,
                "piece_kind": piece_kind,
                "placements": count,
                "known": True,
                "name": _tile_name(path),
                "path": path,
                "family": _tile_family(path),
                "name_tags": list(_name_tags(path)),
                "catalog_size": int(meta["size"]),
            }
        )

    notable_tiles = []
    for index, uuid in sorted(tile_list.items()):
        meta = UNDERGROUND_TILE_METADATA.get(uuid)
        if meta is None:
            continue

        path = str(meta["path"])
        family = _tile_family(path)
        tags = _name_tags(path)

        if family == "elevator" or tags:
            notable_tiles.append(
                {
                    "tile_index": index,
                    "uuid": uuid,
                    "name": _tile_name(path),
                    "family": family,
                    "name_tags": list(tags),
                    "catalog_size": int(meta["size"]),
                }
            )

    return {
        "world_id": world_id,
        "row_id": row_id,
        "catalog_entries": len(UNDERGROUND_TILE_METADATA),
        "tile_list_entries": len(tile_list),
        "known_tile_list_entries": len(known_tile_list),
        "unknown_tile_list_entries": len(unknown_tile_list),
        "unknown_tile_list": [
            {
                "tile_index": index,
                "uuid": uuid,
            }
            for index, uuid in sorted(unknown_tile_list.items())
        ],
        "placements": len(pieces),
        "known_placements": known_piece_count,
        "unknown_placements": len(pieces) - known_piece_count,
        "family_counts": dict(family_counts.most_common()),
        "name_tag_counts": dict(tag_counts.most_common()),
        "notable_tiles": notable_tiles,
        "top_tiles": top_tiles,
    }
