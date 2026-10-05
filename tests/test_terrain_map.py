from __future__ import annotations

from pathlib import Path

from sm_atlas.terrain_chunks import VoxelChunkRecord
from sm_atlas.terrain_map import render_voxel_chunk_map_svg


def record(
    record_id: int,
    x: int,
    y: int,
    z: int,
) -> VoxelChunkRecord:
    return VoxelChunkRecord(
        record_id=record_id,
        cell_x=x // 4,
        cell_y=y // 4,
        chunk_x=x,
        chunk_y=y,
        chunk_z=z,
        marker_offset=1,
        id_offset=4,
        prefix_hex="c0",
        blob_size=100,
        payload_offset=32,
        payload_size=68,
        payload_prefix_hex="0500",
    )


def test_render_voxel_chunk_map_svg_uses_shared_bounds() -> None:
    svg = render_voxel_chunk_map_svg(
        [
            record(1, -2, -3, 0),
            record(2, 1, 2, 0),
            record(3, 0, 0, 1),
        ],
        world_id=23,
    )

    assert svg.startswith('<?xml version="1.0"')
    assert "World 23 · Z=0 · 2 chunks" in svg
    assert "World 23 · Z=1 · 1 chunks" in svg
    assert "X -2..1 · Y -3..2" in svg
    assert svg.count('class="chunk"') == 3
