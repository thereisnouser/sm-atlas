from __future__ import annotations

from collections import Counter
from typing import Any

from .database import SaveDatabase
from .formats.lua_values import (
    LuaColor,
    LuaHandle,
    LuaQuat,
    LuaUuid,
    LuaValueError,
    LuaVec3,
    decode_lua_value,
    to_jsonable,
)
from .terrain_data import TERRAIN_SIGNAL_KEYS
from .terrain_data_probe import (
    ScriptDataEnvelopeError,
    decode_script_data_envelope,
)

DEFAULT_FIELDS = (
    "bounds",
    "tunnels",
    "caves",
    "pockets",
    "spawners",
    "tileList",
    "data",
    "uid",
    "rotation",
    "xOffset",
    "yOffset",
)


def _value_type(value: Any) -> str:
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, LuaUuid):
        return "uuid"
    if isinstance(value, LuaVec3):
        return "vec3"
    if isinstance(value, LuaQuat):
        return "quat"
    if isinstance(value, LuaColor):
        return "color"
    if isinstance(value, LuaHandle):
        return "handle"
    if isinstance(value, dict):
        return "table"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return type(value).__name__


def _preview(
    value: Any,
    *,
    depth: int,
    max_items: int,
) -> Any:
    if depth <= 0:
        if isinstance(value, dict):
            return {
                "<table>": len(value),
            }
        return to_jsonable(value)

    if not isinstance(value, dict):
        return to_jsonable(value)

    output: dict[str, Any] = {}
    items = list(value.items())

    for key, item in items[:max_items]:
        output[str(key)] = _preview(
            item,
            depth=depth - 1,
            max_items=max_items,
        )

    if len(items) > max_items:
        output["<truncated>"] = len(items) - max_items

    return output


def _table_profile(
    value: dict[Any, Any],
    *,
    examples: int,
    depth: int,
    max_items: int,
) -> dict[str, object]:
    key_types = Counter(_value_type(key) for key in value.keys())
    value_types = Counter(_value_type(item) for item in value.values())

    signatures: Counter[str] = Counter()
    for item in value.values():
        if not isinstance(item, dict):
            continue

        string_keys = sorted(
            key
            for key in item.keys()
            if isinstance(key, str)
        )

        if string_keys:
            signature = ", ".join(string_keys)
        else:
            nested_key_types = sorted(
                {
                    _value_type(key)
                    for key in item.keys()
                }
            )
            signature = (
                "<no string keys; "
                + "/".join(nested_key_types)
                + ">"
            )

        signatures[signature] += 1

    sample_items = []
    for key, item in list(value.items())[:examples]:
        sample_items.append(
            {
                "key": to_jsonable(key),
                "value_type": _value_type(item),
                "value": _preview(
                    item,
                    depth=depth,
                    max_items=max_items,
                ),
            }
        )

    return {
        "type": "table",
        "items": len(value),
        "key_types": dict(key_types.most_common()),
        "value_types": dict(value_types.most_common()),
        "nested_signatures": dict(
            signatures.most_common(20)
        ),
        "examples": sample_items,
    }


def _profile_value(
    value: Any,
    *,
    examples: int,
    depth: int,
    max_items: int,
) -> dict[str, object]:
    if isinstance(value, dict):
        return _table_profile(
            value,
            examples=examples,
            depth=depth,
            max_items=max_items,
        )

    return {
        "type": _value_type(value),
        "value": _preview(
            value,
            depth=depth,
            max_items=max_items,
        ),
    }


def probe_terrain_data_structure(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
    examples: int = 3,
    depth: int = 4,
    max_items: int = 8,
) -> dict[str, object]:
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    if not 0 <= examples <= 20:
        raise ValueError("examples must be between 0 and 20")
    if not 1 <= depth <= 8:
        raise ValueError("depth must be between 1 and 8")
    if not 1 <= max_items <= 50:
        raise ValueError("max_items must be between 1 and 50")

    with database.connect() as connection:
        if "ScriptData" not in database._tables(connection):
            rows = []
        else:
            rows = connection.execute(
                """
                SELECT rowid AS row_id, key, data
                FROM ScriptData
                WHERE worldId = ?
                  AND data IS NOT NULL
                ORDER BY length(data) DESC, rowid
                LIMIT ?
                """,
                (world_id, limit),
            ).fetchall()

    failures: Counter[str] = Counter()
    candidates: list[dict[str, Any]] = []

    for row in rows:
        blob = row["data"]
        if not isinstance(blob, bytes):
            failures["not_blob"] += 1
            continue

        try:
            envelope = decode_script_data_envelope(blob)
            value = decode_lua_value(envelope.data)
        except (ScriptDataEnvelopeError, LuaValueError) as exc:
            failures[str(exc)] += 1
            continue

        if not isinstance(value, dict):
            continue

        string_keys = {
            key
            for key in value.keys()
            if isinstance(key, str)
        }
        signal_keys = sorted(
            string_keys.intersection(TERRAIN_SIGNAL_KEYS)
        )

        if not signal_keys:
            continue

        sql_key = row["key"]
        candidates.append(
            {
                "row_id": int(row["row_id"]),
                "sql_key_hex": (
                    bytes(sql_key).hex()
                    if isinstance(sql_key, bytes)
                    else None
                ),
                "raw_size": len(envelope.data),
                "signal_keys": signal_keys,
                "value": value,
            }
        )

    candidates.sort(
        key=lambda item: (
            len(item["signal_keys"]),
            item["raw_size"],
        ),
        reverse=True,
    )

    if not candidates:
        return {
            "world_id": world_id,
            "scanned_records": len(rows),
            "failures": dict(failures.most_common(20)),
            "candidate": None,
        }

    candidate = candidates[0]
    value = candidate["value"]

    fields = {}
    for field in DEFAULT_FIELDS:
        if field not in value:
            continue
        fields[field] = _profile_value(
            value[field],
            examples=examples,
            depth=depth,
            max_items=max_items,
        )

    scalar_root = {
        key: _preview(
            item,
            depth=2,
            max_items=max_items,
        )
        for key, item in value.items()
        if isinstance(key, str)
        and key not in fields
        and not isinstance(item, dict)
    }

    return {
        "world_id": world_id,
        "scanned_records": len(rows),
        "failures": dict(failures.most_common(20)),
        "candidate": {
            "row_id": candidate["row_id"],
            "sql_key_hex": candidate["sql_key_hex"],
            "raw_size": candidate["raw_size"],
            "signal_keys": candidate["signal_keys"],
            "root_keys": sorted(
                key
                for key in value.keys()
                if isinstance(key, str)
            ),
            "scalar_root": scalar_root,
            "fields": fields,
        },
    }
