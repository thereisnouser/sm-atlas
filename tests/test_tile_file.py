from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sm_atlas.tile_file import (
    TILE_CELL_HEADER_SIZE,
    TILE_FILE_HEADER_FORMAT,
    InvalidTileFile,
    decode_tunnel_node_chunk,
    decompress_lz4_block,
    probe_tile,
    probe_tile_chunks,
)


def _write_test_tile(path: Path) -> None:
    header_size = struct.calcsize(TILE_FILE_HEADER_FORMAT)
    cell_header_offset = header_size
    cell_header_size = TILE_CELL_HEADER_SIZE

    header = struct.pack(
        TILE_FILE_HEADER_FORMAT,
        0x454C4954,
        9,
        bytes.fromhex("00112233445566778899aabbccddeeff"),
        123456789,
        1,
        1,
        cell_header_offset,
        cell_header_size,
        11,
        22,
        3,
    )

    values = [0] * 97

    # assets level 2
    values[21 + 2] = 5
    values[25 + 2] = header_size + cell_header_size
    values[29 + 2] = 8
    values[33 + 2] = 32

    # node
    values[41] = 2
    values[42] = header_size + cell_header_size + 8
    node_payload = bytes(range(24))
    node_compressed = bytes((0xF0, 9)) + node_payload
    values[43] = len(node_compressed)
    values[44] = len(node_payload)

    cell_header = struct.pack("<97i", *values)
    payload = b"12345678" + node_compressed

    path.write_bytes(header + cell_header + payload)


def test_probe_tile_reads_header_and_chunk_inventory(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sample.tile"
    _write_test_tile(path)

    result = probe_tile(path)

    assert result["version"] == 9
    assert result["width"] == 1
    assert result["height"] == 1
    assert result["cells"] == 1
    assert result["uuid_hex"] == (
        "00112233445566778899aabbccddeeff"
    )
    assert result["content"]["assets"] == {
        "chunks": 1,
        "items": 5,
        "compressed_bytes": 8,
        "uncompressed_bytes": 32,
    }
    assert result["content"]["node"] == {
        "chunks": 1,
        "items": 2,
        "compressed_bytes": 26,
        "uncompressed_bytes": 24,
    }
    assert result["invalid_chunk_ranges"] == []


def test_probe_tile_rejects_wrong_magic(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bad.tile"
    path.write_bytes(b"NOPE" + b"\x00" * 100)

    with pytest.raises(InvalidTileFile):
        probe_tile(path)



def test_decompress_lz4_block_literal_only() -> None:
    compressed = bytes((0xB0,)) + b"hello world"

    assert decompress_lz4_block(
        compressed,
        expected_size=11,
    ) == b"hello world"


def test_decompress_lz4_block_with_match() -> None:
    compressed = bytes((0x32,)) + b"abc" + b"\x03\x00"

    assert decompress_lz4_block(
        compressed,
        expected_size=9,
    ) == b"abcabcabc"


def test_probe_tile_chunks_decompresses_selected_chunk(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sample.tile"
    _write_test_tile(path)

    result = probe_tile_chunks(
        path,
        kind="node",
        full_hex=True,
    )

    assert len(result["chunks"]) == 1
    chunk = result["chunks"][0]
    assert chunk["cell"] == 0
    assert chunk["count"] == 2
    assert chunk["decoded_size"] == 24
    assert chunk["hex"] == bytes(range(24)).hex()
    assert chunk["hex_prefix"] == bytes(range(24)).hex()



def test_decode_tunnel_node_chunk_reads_transform_and_params() -> None:
    header = b"\x01\x06TUNNEL"
    transform = (
        struct.pack("<3f", 18.666666, 2.666667, 8.0)
        + struct.pack("<4f", 1.0, 0.0, 0.0, 0.0)
        + struct.pack("<3f", 4.0, 4.0, 4.0)
    )
    metadata = (
        b"\x01\x00\x47\x00\x00\x00LUA\x00\x00\x00"
        b"\x01\x05\x00\x00\x00\x01\x02\x00\x00\x00"
        b"\x03\x00tunnel"
        + bytes.fromhex("0c866c52e429a84bbf3341b2bf7b626186")
    )
    params = b'{"tunnel":{"type":"Main"}}'
    record = (
        transform
        + metadata
        + len(params).to_bytes(4, "big")
        + params
    )

    nodes = decode_tunnel_node_chunk(
        header + record,
        expected_count=1,
    )

    assert len(nodes) == 1
    node = nodes[0]
    assert node["position"] == pytest.approx(
        (18.666666, 2.666667, 8.0),
    )
    assert node["rotation"] == pytest.approx(
        (1.0, 0.0, 0.0, 0.0),
    )
    assert node["scale"] == pytest.approx(
        (4.0, 4.0, 4.0),
    )
    assert node["tags"] == ["tunnel"]
    assert node["params"] == {
        "tunnel": {
            "type": "Main",
        }
    }
    assert node["record_size"] == len(record)
