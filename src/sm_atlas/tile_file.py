from __future__ import annotations

import hashlib
import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path


TILE_MAGIC = 0x454C4954
TILE_FILE_HEADER_FORMAT = "<II16sQIIIIIII"
TILE_FILE_HEADER_SIZE = struct.calcsize(TILE_FILE_HEADER_FORMAT)
TILE_CELL_HEADER_INTS = 97
TILE_CELL_HEADER_SIZE = TILE_CELL_HEADER_INTS * 4
TILE_CELL_SIZE_METERS = 64.0


class InvalidTileFile(ValueError):
    """Raised when a file does not look like a Scrap Mechanic .tile file."""


@dataclass(frozen=True)
class TileChunk:
    cell: int
    kind: str
    level: int | None
    count: int | None
    index: int
    compressed_size: int
    uncompressed_size: int

    def to_dict(self) -> dict[str, object]:
        return {
            "cell": self.cell,
            "kind": self.kind,
            "level": self.level,
            "count": self.count,
            "index": self.index,
            "compressed_size": self.compressed_size,
            "uncompressed_size": self.uncompressed_size,
        }


def _single_chunk(
    values: tuple[int, ...],
    *,
    cell: int,
    kind: str,
    base: int,
) -> TileChunk:
    count = values[base]
    index = values[base + 1]
    compressed = values[base + 2]
    size = values[base + 3]
    return TileChunk(
        cell=cell,
        kind=kind,
        level=None,
        count=count,
        index=index,
        compressed_size=compressed,
        uncompressed_size=size,
    )


def _level_chunks(
    values: tuple[int, ...],
    *,
    cell: int,
    kind: str,
    count_slice: slice | None,
    index_slice: slice,
    compressed_slice: slice,
    size_slice: slice,
) -> list[TileChunk]:
    indexes = values[index_slice]
    compressed = values[compressed_slice]
    sizes = values[size_slice]
    counts = (
        (None,) * len(indexes)
        if count_slice is None
        else values[count_slice]
    )
    return [
        TileChunk(
            cell=cell,
            kind=kind,
            level=level,
            count=counts[level],
            index=indexes[level],
            compressed_size=compressed[level],
            uncompressed_size=sizes[level],
        )
        for level in range(len(indexes))
    ]


def _parse_cell_chunks(
    data: bytes,
    *,
    offset: int,
    size: int,
    cell: int,
) -> list[TileChunk]:
    if size < TILE_CELL_HEADER_SIZE:
        raise InvalidTileFile(
            f"cell header size {size} is smaller than "
            f"{TILE_CELL_HEADER_SIZE}"
        )
    if offset < 0 or offset + TILE_CELL_HEADER_SIZE > len(data):
        raise InvalidTileFile("cell header extends beyond file")

    values = struct.unpack_from(
        f"<{TILE_CELL_HEADER_INTS}i",
        data,
        offset,
    )

    chunks: list[TileChunk] = []
    chunks.extend(
        _level_chunks(
            values,
            cell=cell,
            kind="mip",
            count_slice=None,
            index_slice=slice(0, 6),
            compressed_slice=slice(6, 12),
            size_slice=slice(12, 18),
        )
    )
    chunks.append(
        TileChunk(
            cell=cell,
            kind="clutter",
            level=None,
            count=None,
            index=values[18],
            compressed_size=values[19],
            uncompressed_size=values[20],
        )
    )
    chunks.extend(
        _level_chunks(
            values,
            cell=cell,
            kind="assets",
            count_slice=slice(21, 25),
            index_slice=slice(25, 29),
            compressed_slice=slice(29, 33),
            size_slice=slice(33, 37),
        )
    )

    for kind, base in (
        ("blueprint", 37),
        ("node", 41),
        ("script", 45),
        ("prefab", 49),
        ("decal", 53),
    ):
        chunks.append(
            _single_chunk(
                values,
                cell=cell,
                kind=kind,
                base=base,
            )
        )

    chunks.extend(
        _level_chunks(
            values,
            cell=cell,
            kind="harvestable",
            count_slice=slice(57, 61),
            index_slice=slice(61, 65),
            compressed_slice=slice(65, 69),
            size_slice=slice(69, 73),
        )
    )
    chunks.extend(
        _level_chunks(
            values,
            cell=cell,
            kind="kinematics",
            count_slice=slice(73, 77),
            index_slice=slice(77, 81),
            compressed_slice=slice(81, 85),
            size_slice=slice(85, 89),
        )
    )
    chunks.append(
        _single_chunk(
            values,
            cell=cell,
            kind="unknown",
            base=89,
        )
    )
    chunks.append(
        _single_chunk(
            values,
            cell=cell,
            kind="voxel_terrain",
            base=93,
        )
    )

    return chunks


def _chunk_present(chunk: TileChunk) -> bool:
    return (
        chunk.index > 0
        and chunk.compressed_size > 0
        and chunk.uncompressed_size > 0
    )


def _read_lz4_length(
    data: bytes,
    offset: int,
    initial: int,
) -> tuple[int, int]:
    length = initial
    if initial != 15:
        return length, offset

    while True:
        if offset >= len(data):
            raise InvalidTileFile("truncated LZ4 length")
        value = data[offset]
        offset += 1
        length += value
        if value != 255:
            return length, offset


def decompress_lz4_block(
    data: bytes,
    *,
    expected_size: int | None = None,
) -> bytes:
    """Decode a raw LZ4 block without adding a runtime dependency."""

    output = bytearray()
    offset = 0

    while offset < len(data):
        token = data[offset]
        offset += 1

        literal_length, offset = _read_lz4_length(
            data,
            offset,
            token >> 4,
        )
        literal_end = offset + literal_length
        if literal_end > len(data):
            raise InvalidTileFile("truncated LZ4 literals")

        output.extend(data[offset:literal_end])
        offset = literal_end

        if offset == len(data):
            break

        if offset + 2 > len(data):
            raise InvalidTileFile("truncated LZ4 match offset")
        match_offset = int.from_bytes(
            data[offset:offset + 2],
            "little",
        )
        offset += 2
        if match_offset <= 0 or match_offset > len(output):
            raise InvalidTileFile(
                f"invalid LZ4 match offset {match_offset}"
            )

        match_length, offset = _read_lz4_length(
            data,
            offset,
            token & 0x0F,
        )
        match_length += 4

        start = len(output) - match_offset
        for index in range(match_length):
            output.append(output[start + index])

    result = bytes(output)
    if (
        expected_size is not None
        and len(result) != expected_size
    ):
        raise InvalidTileFile(
            "LZ4 size mismatch: "
            f"expected {expected_size}, got {len(result)}"
        )
    return result


def _ascii_strings(
    data: bytes,
    *,
    minimum_length: int = 4,
) -> list[str]:
    pattern = rb"[ -~]{" + str(minimum_length).encode() + rb",}"
    return [
        match.group(0).decode("ascii")
        for match in re.finditer(pattern, data)
    ]


def _float32_candidates(
    data: bytes,
    *,
    limit: int = 64,
) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for offset in range(0, len(data) - 3, 4):
        value = struct.unpack_from("<f", data, offset)[0]
        if not (-100000.0 <= value <= 100000.0):
            continue
        if value != value:
            continue
        if abs(value) < 1e-12 and value != 0.0:
            continue
        values.append(
            {
                "offset": offset,
                "hex": data[offset:offset + 4].hex(),
                "value": round(float(value), 9),
            }
        )
        if len(values) >= limit:
            break
    return values


def _find_json_payload(
    data: bytes,
    *,
    start: int,
) -> tuple[int, int, object]:
    for json_start in range(start + 4, len(data)):
        if data[json_start] not in (ord("{"), ord("[")):
            continue

        length = int.from_bytes(
            data[json_start - 4:json_start],
            "big",
        )
        if length <= 0:
            continue
        json_end = json_start + length
        if json_end > len(data):
            continue

        try:
            value = json.loads(
                data[json_start:json_end].decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue

        return json_start, json_end, value

    raise InvalidTileFile(
        "could not locate length-prefixed node params JSON"
    )


TUNNEL_NODE_METADATA = bytes.fromhex(
    "0100470000004c554100000001050000000102000000030074756e6e656c"
    "0c866c52e429a84bbf3341b2bf7b626186"
)


def decode_tunnel_node_chunk(
    data: bytes,
    *,
    expected_count: int | None = None,
) -> list[dict[str, object]]:
    """Extract TUNNEL node records from simple or mixed node chunks.

    The first byte is the number of node groups in the chunk. Some chunks
    contain only one TUNNEL group, while larger terrain cells can contain
    several different node groups. TUNNEL records have a stable metadata
    signature followed by a big-endian JSON length and params payload.
    """

    if len(data) < 8:
        raise InvalidTileFile("node chunk is too small")

    group_count = data[0]
    if group_count <= 0:
        raise InvalidTileFile("node chunk has no groups")

    nodes: list[dict[str, object]] = []
    search_from = 1

    while True:
        metadata_offset = data.find(
            TUNNEL_NODE_METADATA,
            search_from,
        )
        if metadata_offset < 0:
            break

        record_offset = metadata_offset - 40
        if record_offset < 0:
            raise InvalidTileFile(
                "TUNNEL metadata appears before transform"
            )

        json_length_offset = (
            metadata_offset + len(TUNNEL_NODE_METADATA)
        )
        if json_length_offset + 4 > len(data):
            raise InvalidTileFile(
                "truncated TUNNEL params length"
            )

        json_length = int.from_bytes(
            data[
                json_length_offset:
                json_length_offset + 4
            ],
            "big",
        )
        json_start = json_length_offset + 4
        json_end = json_start + json_length
        if json_end > len(data):
            raise InvalidTileFile(
                "truncated TUNNEL params JSON"
            )

        try:
            params = json.loads(
                data[json_start:json_end].decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidTileFile(
                "invalid TUNNEL params JSON"
            ) from exc

        tunnel = (
            params.get("tunnel")
            if isinstance(params, dict)
            else None
        )
        if not isinstance(tunnel, dict):
            search_from = metadata_offset + 1
            continue

        position = struct.unpack_from(
            "<3f",
            data,
            record_offset,
        )
        rotation = struct.unpack_from(
            "<4f",
            data,
            record_offset + 12,
        )
        scale = struct.unpack_from(
            "<3f",
            data,
            record_offset + 28,
        )

        metadata = data[
            record_offset + 40:
            metadata_offset + len(TUNNEL_NODE_METADATA)
        ]
        strings = _ascii_strings(
            metadata,
            minimum_length=3,
        )
        tags = [
            value
            for value in strings
            if value.isalpha() and value.islower()
        ]

        nodes.append(
            {
                "index": len(nodes),
                "position": tuple(
                    float(value)
                    for value in position
                ),
                "rotation": tuple(
                    float(value)
                    for value in rotation
                ),
                "scale": tuple(
                    float(value)
                    for value in scale
                ),
                "tags": tags,
                "params": params,
                "metadata_hex": metadata.hex(),
                "metadata_strings": strings,
                "record_offset": record_offset,
                "record_size": json_end - record_offset,
            }
        )
        search_from = json_end

    if group_count == 1 and expected_count is not None:
        if len(nodes) != expected_count:
            raise InvalidTileFile(
                "TUNNEL node count mismatch: "
                f"expected {expected_count}, got {len(nodes)}"
            )

    return nodes


def probe_tile_nodes(
    path: str | Path,
) -> dict[str, object]:
    tile_path = Path(path).expanduser().resolve()
    tile = probe_tile(tile_path)
    data = tile_path.read_bytes()
    width = int(tile["width"])

    node_chunks = [
        chunk
        for chunk in tile["chunks"]
        if chunk["kind"] == "node"
    ]
    decoded_chunks = []

    for meta in node_chunks:
        compressed = data[
            meta["index"]:
            meta["index"] + meta["compressed_size"]
        ]
        decoded = decompress_lz4_block(
            compressed,
            expected_size=meta["uncompressed_size"],
        )
        nodes = decode_tunnel_node_chunk(
            decoded,
            expected_count=meta["count"],
        )

        cell = int(meta["cell"])
        cell_x = cell % width
        cell_y = cell // width

        for node in nodes:
            position = node["position"]
            node["tile_position"] = (
                float(position[0])
                + cell_x * TILE_CELL_SIZE_METERS,
                float(position[1])
                + cell_y * TILE_CELL_SIZE_METERS,
                float(position[2]),
            )

        decoded_chunks.append(
            {
                "cell": cell,
                "cell_x": cell_x,
                "cell_y": cell_y,
                "cell_offset": (
                    cell_x * TILE_CELL_SIZE_METERS,
                    cell_y * TILE_CELL_SIZE_METERS,
                    0.0,
                ),
                "count": meta["count"],
                "nodes": nodes,
            }
        )

    return {
        "path": str(tile_path),
        "uuid_hex": tile["uuid_hex"],
        "width": tile["width"],
        "height": tile["height"],
        "node_chunks": decoded_chunks,
        "nodes": sum(
            len(chunk["nodes"])
            for chunk in decoded_chunks
        ),
    }


VOXEL_RECORD_SIZE = 4108
VOXEL_PAYLOAD_SIZE = 16 * 16 * 16


def probe_tile_voxels(
    path: str | Path,
    *,
    cell: int | None = None,
    examples: int = 20,
) -> dict[str, object]:
    if examples < 1:
        raise ValueError("examples must be >= 1")

    tile_path = Path(path).expanduser().resolve()
    tile = probe_tile(tile_path)
    data = tile_path.read_bytes()

    selected = [
        chunk
        for chunk in tile["chunks"]
        if chunk["kind"] == "voxel_terrain"
        and (cell is None or chunk["cell"] == cell)
    ]
    if not selected:
        raise ValueError(
            "no voxel_terrain chunks"
            + (
                ""
                if cell is None
                else f" in cell {cell}"
            )
        )

    chunk_results = []
    all_headers: list[tuple[int, int, int]] = []
    total_records = 0
    total_payload_bytes = 0
    global_histogram = [0] * 256

    for meta in selected:
        compressed = data[
            meta["index"]:
            meta["index"] + meta["compressed_size"]
        ]
        decoded = decompress_lz4_block(
            compressed,
            expected_size=meta["uncompressed_size"],
        )

        expected_count = int(meta["count"] or 0)
        if len(decoded) % VOXEL_RECORD_SIZE != 0:
            raise InvalidTileFile(
                "voxel_terrain chunk is not aligned to "
                f"{VOXEL_RECORD_SIZE}-byte records"
            )
        record_count = len(decoded) // VOXEL_RECORD_SIZE
        if expected_count and record_count != expected_count:
            raise InvalidTileFile(
                "voxel_terrain record count mismatch: "
                f"expected {expected_count}, got {record_count}"
            )

        examples_out = []
        headers = []
        for index in range(record_count):
            start = index * VOXEL_RECORD_SIZE
            record = decoded[start:start + VOXEL_RECORD_SIZE]
            header = struct.unpack_from("<3i", record, 0)
            payload = record[12:]
            if len(payload) != VOXEL_PAYLOAD_SIZE:
                raise InvalidTileFile(
                    "unexpected voxel payload size "
                    f"{len(payload)}"
                )

            headers.append(header)
            all_headers.append(header)
            total_records += 1
            total_payload_bytes += len(payload)

            local_hist = [0] * 256
            for value in payload:
                local_hist[value] += 1
                global_histogram[value] += 1
                material_hist[value >> 4] += 1
                density_hist[value & 0x0F] += 1

            if len(examples_out) < examples:
                nonzero = VOXEL_PAYLOAD_SIZE - local_hist[0]
                non255 = VOXEL_PAYLOAD_SIZE - local_hist[255]
                top_values = sorted(
                    (
                        (count, value)
                        for value, count in enumerate(local_hist)
                        if count
                    ),
                    reverse=True,
                )[:8]
                examples_out.append(
                    {
                        "index": index,
                        "header_i32": header,
                        "header_hex": record[:12].hex(),
                        "payload_min": min(payload),
                        "payload_max": max(payload),
                        "unique_values": sum(
                            count > 0
                            for count in local_hist
                        ),
                        "zero_count": local_hist[0],
                        "nonzero_count": nonzero,
                        "ff_count": local_hist[255],
                        "non_ff_count": non255,
                        "top_values": [
                            {
                                "value": value,
                                "count": count,
                            }
                            for count, value in top_values
                        ],
                        "payload_sha256": hashlib.sha256(
                            payload
                        ).hexdigest(),
                        "material_histogram": material_hist,
                        "density_histogram": density_hist,
                    }
                )

        chunk_results.append(
            {
                "cell": meta["cell"],
                "records": record_count,
                "decoded_size": len(decoded),
                "headers_min": (
                    tuple(
                        min(header[axis] for header in headers)
                        for axis in range(3)
                    )
                    if headers
                    else None
                ),
                "headers_max": (
                    tuple(
                        max(header[axis] for header in headers)
                        for axis in range(3)
                    )
                    if headers
                    else None
                ),
                "examples": examples_out,
            }
        )

    global_top = sorted(
        (
            (count, value)
            for value, count in enumerate(global_histogram)
            if count
        ),
        reverse=True,
    )[:16]

    unique_headers = len(set(all_headers))
    return {
        "path": str(tile_path),
        "record_size": VOXEL_RECORD_SIZE,
        "payload_size": VOXEL_PAYLOAD_SIZE,
        "records": total_records,
        "unique_headers": unique_headers,
        "payload_bytes": total_payload_bytes,
        "header_bounds": (
            {
                "min": tuple(
                    min(header[axis] for header in all_headers)
                    for axis in range(3)
                ),
                "max": tuple(
                    max(header[axis] for header in all_headers)
                    for axis in range(3)
                ),
            }
            if all_headers
            else None
        ),
        "global_top_values": [
            {
                "value": value,
                "count": count,
            }
            for count, value in global_top
        ],
        "chunks": chunk_results,
    }


def probe_tile_chunks(
    path: str | Path,
    *,
    kind: str,
    cell: int | None = None,
    full_hex: bool = False,
) -> dict[str, object]:
    tile_path = Path(path).expanduser().resolve()
    tile = probe_tile(tile_path)
    data = tile_path.read_bytes()

    selected = [
        chunk
        for chunk in tile["chunks"]
        if chunk["kind"] == kind
        and (cell is None or chunk["cell"] == cell)
    ]
    if not selected:
        raise ValueError(
            f"no {kind!r} chunks"
            + (
                ""
                if cell is None
                else f" in cell {cell}"
            )
        )

    chunks = []
    for meta in selected:
        compressed = data[
            meta["index"]:
            meta["index"] + meta["compressed_size"]
        ]
        decoded = decompress_lz4_block(
            compressed,
            expected_size=meta["uncompressed_size"],
        )

        item = dict(meta)
        item.update(
            {
                "sha256": hashlib.sha256(decoded).hexdigest(),
                "decoded_size": len(decoded),
                "hex_prefix": decoded[:128].hex(),
                "hex_suffix": decoded[-64:].hex(),
                "ascii_strings": _ascii_strings(decoded),
                "float32_le_candidates": _float32_candidates(decoded),
            }
        )
        if full_hex:
            item["hex"] = decoded.hex()
        chunks.append(item)

    return {
        "path": str(tile_path),
        "kind": kind,
        "chunks": chunks,
    }


def probe_tile(path: str | Path) -> dict[str, object]:
    tile_path = Path(path).expanduser().resolve()
    if not tile_path.is_file():
        raise FileNotFoundError(tile_path)

    data = tile_path.read_bytes()
    if len(data) < TILE_FILE_HEADER_SIZE:
        raise InvalidTileFile("file is smaller than the .tile header")

    (
        magic,
        version,
        uuid_bytes,
        creator_id,
        width,
        height,
        cell_header_offset,
        cell_header_size,
        unknown_1,
        unknown_2,
        tile_type,
    ) = struct.unpack_from(
        TILE_FILE_HEADER_FORMAT,
        data,
        0,
    )

    if magic != TILE_MAGIC:
        raise InvalidTileFile("missing TILE magic")
    if width <= 0 or height <= 0:
        raise InvalidTileFile(
            f"invalid tile dimensions: {width}x{height}"
        )

    cell_count = width * height
    header_end = (
        cell_header_offset
        + cell_header_size * cell_count
    )
    if cell_header_offset < TILE_FILE_HEADER_SIZE:
        raise InvalidTileFile("cell header offset overlaps file header")
    if header_end > len(data):
        raise InvalidTileFile("cell header table extends beyond file")

    chunks: list[TileChunk] = []
    for cell in range(cell_count):
        chunks.extend(
            _parse_cell_chunks(
                data,
                offset=cell_header_offset + cell * cell_header_size,
                size=cell_header_size,
                cell=cell,
            )
        )

    present = [
        chunk
        for chunk in chunks
        if _chunk_present(chunk)
    ]

    invalid_ranges = []
    for chunk in present:
        end = chunk.index + chunk.compressed_size
        if chunk.index < 0 or end > len(data):
            invalid_ranges.append(chunk.to_dict())

    kinds: dict[str, dict[str, int]] = {}
    for chunk in present:
        summary = kinds.setdefault(
            chunk.kind,
            {
                "chunks": 0,
                "items": 0,
                "compressed_bytes": 0,
                "uncompressed_bytes": 0,
            },
        )
        summary["chunks"] += 1
        summary["items"] += max(chunk.count or 0, 0)
        summary["compressed_bytes"] += chunk.compressed_size
        summary["uncompressed_bytes"] += chunk.uncompressed_size

    return {
        "path": str(tile_path),
        "file_size": len(data),
        "version": version,
        "uuid_hex": uuid_bytes.hex(),
        "creator_id": creator_id,
        "width": width,
        "height": height,
        "cells": cell_count,
        "cell_header_offset": cell_header_offset,
        "cell_header_size": cell_header_size,
        "unknown_1": unknown_1,
        "unknown_2": unknown_2,
        "type": tile_type,
        "content": kinds,
        "invalid_chunk_ranges": invalid_ranges,
        "chunks": [
            chunk.to_dict()
            for chunk in present
        ],
    }
