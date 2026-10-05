from __future__ import annotations

from dataclasses import dataclass
from struct import unpack_from

from .lz4 import decompress_block

WORLD_MARKER_UID = bytes.fromhex(
    "5297769df4514e5e9a388b0f95e2edad"
)


class GenericDataError(ValueError):
    """Raised when a GenericData record cannot be decoded."""


@dataclass(frozen=True)
class GenericDataEnvelope:
    uid: bytes
    channel: int
    key: int
    world_id: int
    flags: int
    compressed_size: int
    data: bytes


def decode_envelope(blob: bytes) -> GenericDataEnvelope:
    if len(blob) < 0x1D:
        raise GenericDataError("GenericData envelope is too short")

    uid = blob[:16]
    channel = unpack_from(">H", blob, 0x10)[0]
    key = unpack_from("<I", blob, 0x12)[0]
    world_id = unpack_from(">H", blob, 0x16)[0]
    flags = unpack_from("<I", blob, 0x18)[0]
    compressed_size = blob[0x1C]

    compressed = blob[0x1D:]
    if compressed_size and compressed_size <= len(compressed):
        compressed = compressed[:compressed_size]

    try:
        data = decompress_block(
            compressed,
            max_output_size=1024 * 1024,
        )
    except ValueError as exc:
        raise GenericDataError(
            f"failed to decompress GenericData payload: {exc}"
        ) from exc

    return GenericDataEnvelope(
        uid=uid,
        channel=channel,
        key=key,
        world_id=world_id,
        flags=flags,
        compressed_size=compressed_size,
        data=data,
    )
