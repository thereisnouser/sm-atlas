from __future__ import annotations

from sm_atlas.terrain_decode import DecodedVoxelRecord
from sm_atlas.terrain_map import render_voxel_chunk_map_svg


def record(
    record_id: int,
    x: int,
    y: int,
    z: int,
) -> DecodedVoxelRecord:
    return DecodedVoxelRecord(
        record_id=record_id,
        cell_x=x // 4,
        cell_y=y // 4,
        chunk_x=x,
        chunk_y=y,
        chunk_z=z,
        compressed_size=100,
        decompressed_size=35,
        header_hex="",
        payload=b"test",
    )


def test_render_voxel_chunk_map_svg_uses_shared_bounds() -> None:
    svg = render_voxel_chunk_map_svg(
        [
            record(1, -2, -3, -1),
            record(2, 1, 2, 0),
            record(3, 0, 0, 1),
        ],
        world_id=23,
    )

    assert svg.startswith('<?xml version="1.0"')
    assert "World 23 · Z=-1 · 1 chunks" in svg
    assert "World 23 · Z=0 · 1 chunks" in svg
    assert "World 23 · Z=1 · 1 chunks" in svg
    assert "X -2..1 · Y -3..2" in svg
    assert svg.count('class="chunk"') == 3
