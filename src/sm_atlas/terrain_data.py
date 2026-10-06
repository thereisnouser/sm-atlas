from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from .database import SaveDatabase
from .formats.lua_values import (
    LuaValueError,
    decode_lua_value,
)
from .terrain_data_probe import (
    ScriptDataEnvelopeError,
    decode_script_data_envelope,
)

TERRAIN_SIGNAL_KEYS = {
    "bounds",
    "caves",
    "pockets",
    "rotation",
    "spawners",
    "tileList",
    "tunnels",
    "uid",
    "xOffset",
    "yOffset",
}


@dataclass(frozen=True)
class TerrainDataCandidate:
    row_id: int
    sql_key_hex: str | None
    raw_size: int
    keys: tuple[str, ...]
    signal_keys: tuple[str, ...]
    value: dict[Any, Any]

    def summary(self) -> dict[str, object]:
        return {
            "row_id": self.row_id,
            "sql_key_hex": self.sql_key_hex,
            "raw_size": self.raw_size,
            "keys": list(self.keys),
            "signal_keys": list(self.signal_keys),
            "fields": {
                key: _summarize_value(self.value[key])
                for key in self.signal_keys
                if key in self.value
            },
        }


def _summarize_value(value: Any) -> dict[str, object]:
    if isinstance(value, dict):
        keys = list(value.keys())
        return {
            "type": "table",
            "items": len(value),
            "key_preview": [
                str(key)
                for key in keys[:12]
            ],
        }

    if isinstance(value, str):
        return {
            "type": "string",
            "length": len(value),
            "preview": value[:120],
        }

    if isinstance(value, bool):
        return {
            "type": "bool",
            "value": value,
        }

    if isinstance(value, (int, float)):
        return {
            "type": type(value).__name__,
            "value": value,
        }

    return {
        "type": type(value).__name__,
        "value": str(value),
    }


def decode_terrain_data_candidates(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
    examples: int = 10,
) -> dict[str, object]:
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    if not 0 <= examples <= 100:
        raise ValueError("examples must be between 0 and 100")

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

    envelope_failures: Counter[str] = Counter()
    lua_failures: Counter[str] = Counter()
    decoded_tables = 0
    candidates: list[TerrainDataCandidate] = []

    for row in rows:
        blob = row["data"]
        if not isinstance(blob, bytes):
            envelope_failures["not_blob"] += 1
            continue

        try:
            envelope = decode_script_data_envelope(blob)
        except ScriptDataEnvelopeError as exc:
            envelope_failures[str(exc)] += 1
            continue

        try:
            value = decode_lua_value(envelope.data)
        except LuaValueError as exc:
            lua_failures[str(exc)] += 1
            continue

        if not isinstance(value, dict):
            continue

        decoded_tables += 1

        string_keys = tuple(
            sorted(
                key
                for key in value.keys()
                if isinstance(key, str)
            )
        )
        signal_keys = tuple(
            key
            for key in string_keys
            if key in TERRAIN_SIGNAL_KEYS
        )

        if not signal_keys:
            continue

        sql_key = row["key"]
        sql_key_hex = (
            bytes(sql_key).hex()
            if isinstance(sql_key, bytes)
            else None
        )

        candidates.append(
            TerrainDataCandidate(
                row_id=int(row["row_id"]),
                sql_key_hex=sql_key_hex,
                raw_size=len(envelope.data),
                keys=string_keys,
                signal_keys=signal_keys,
                value=value,
            )
        )

    candidates.sort(
        key=lambda candidate: (
            len(candidate.signal_keys),
            candidate.raw_size,
        ),
        reverse=True,
    )

    return {
        "world_id": world_id,
        "scanned_records": len(rows),
        "decoded_tables": decoded_tables,
        "envelope_failures": dict(
            envelope_failures.most_common(20)
        ),
        "lua_failures": dict(lua_failures.most_common(20)),
        "terrain_candidates": len(candidates),
        "candidates": [
            candidate.summary()
            for candidate in candidates[:examples]
        ],
    }
