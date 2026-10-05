from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from struct import unpack_from

from .database import SaveDatabase
from .formats.lz4 import Lz4BlockError, decompress_block

LUA_MAGIC = b"LUA"


class ScriptDataEnvelopeError(ValueError):
    """Raised when a ScriptData BLOB envelope cannot be decoded."""


@dataclass(frozen=True)
class ScriptDataEnvelope:
    uid: bytes
    key: bytes
    world_id: int
    flags: int
    compressed_size: int
    data: bytes


def decode_script_data_envelope(blob: bytes) -> ScriptDataEnvelope:
    if len(blob) < 25:
        raise ScriptDataEnvelopeError("ScriptData envelope is too short")

    key_size = unpack_from(">H", blob, 16)[0]
    key_start = 18
    key_end = key_start + key_size
    trailer_end = key_end + 7

    if trailer_end > len(blob):
        raise ScriptDataEnvelopeError("truncated ScriptData envelope")

    world_id = unpack_from(">H", blob, key_end)[0]
    flags = blob[key_end + 2]
    compressed_size = unpack_from(">I", blob, key_end + 3)[0]

    compressed_start = trailer_end
    compressed_end = compressed_start + compressed_size

    if compressed_end > len(blob):
        raise ScriptDataEnvelopeError("truncated ScriptData payload")

    if compressed_end != len(blob):
        raise ScriptDataEnvelopeError("trailing ScriptData envelope bytes")

    try:
        data = decompress_block(
            blob[compressed_start:compressed_end],
            max_output_size=32 * 1024 * 1024,
        )
    except Lz4BlockError as exc:
        raise ScriptDataEnvelopeError(
            f"failed to decompress ScriptData payload: {exc}"
        ) from exc

    return ScriptDataEnvelope(
        uid=blob[:16],
        key=blob[key_start:key_end],
        world_id=world_id,
        flags=flags,
        compressed_size=compressed_size,
        data=data,
    )


def probe_terrain_script_data(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
    examples: int = 20,
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
                SELECT rowid AS row_id, uid, key, worldId, flags, data
                FROM ScriptData
                WHERE worldId = ?
                  AND data IS NOT NULL
                ORDER BY length(data) DESC, rowid
                LIMIT ?
                """,
                (world_id, limit),
            ).fetchall()

    decoded = []
    failures: Counter[str] = Counter()
    magic_counts: Counter[str] = Counter()
    lua_records = []

    for row in rows:
        blob = row["data"]
        if not isinstance(blob, bytes):
            failures["not_blob"] += 1
            continue

        try:
            envelope = decode_script_data_envelope(blob)
        except ScriptDataEnvelopeError as exc:
            message = str(exc)
            if "decompress" in message:
                failures["lz4"] += 1
            elif "trailing" in message:
                failures["trailing"] += 1
            elif "truncated" in message:
                failures["truncated"] += 1
            else:
                failures["envelope"] += 1
            continue

        if envelope.world_id != int(row["worldId"]):
            failures["world_id_mismatch"] += 1
            continue

        prefix = envelope.data[:4]
        magic = prefix.hex() if prefix else "<empty>"
        magic_counts[magic] += 1

        item = {
            "row_id": int(row["row_id"]),
            "sql_flags": int(row["flags"]),
            "envelope_flags": envelope.flags,
            "sql_uid_hex": (
                bytes(row["uid"]).hex()
                if isinstance(row["uid"], bytes)
                else None
            ),
            "envelope_uid_hex": envelope.uid.hex(),
            "sql_key_hex": (
                bytes(row["key"]).hex()
                if isinstance(row["key"], bytes)
                else None
            ),
            "envelope_key_hex": envelope.key.hex(),
            "blob_size": len(blob),
            "compressed_size": envelope.compressed_size,
            "raw_size": len(envelope.data),
            "raw_prefix_hex": envelope.data[:32].hex(),
            "lua_magic": envelope.data.startswith(LUA_MAGIC),
        }
        decoded.append(item)

        if item["lua_magic"]:
            lua_records.append(item)

    return {
        "world_id": world_id,
        "scanned_records": len(rows),
        "decoded_envelopes": len(decoded),
        "decode_failures": dict(failures.most_common()),
        "raw_prefixes": dict(magic_counts.most_common(30)),
        "lua_records": len(lua_records),
        "largest_lua_records": lua_records[:examples],
        "examples": decoded[:examples],
    }
