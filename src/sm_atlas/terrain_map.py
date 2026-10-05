from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from .database import SaveDatabase
from .terrain_decode import DecodedVoxelRecord, decode_voxel_records

CELL_SIZE = 10
PANEL_PADDING = 22
TITLE_HEIGHT = 44
PANEL_GAP = 28
PANELS_PER_ROW = 4


def _bounds(
    records: list[DecodedVoxelRecord],
) -> tuple[int, int, int, int]:
    return (
        min(record.chunk_x for record in records),
        max(record.chunk_x for record in records),
        min(record.chunk_y for record in records),
        max(record.chunk_y for record in records),
    )


def render_voxel_chunk_map_svg(
    records: list[DecodedVoxelRecord],
    *,
    world_id: int,
) -> str:
    if not records:
        raise ValueError("no decoded voxel chunk coordinates")

    min_x, max_x, min_y, max_y = _bounds(records)
    grid_width = max_x - min_x + 1
    grid_height = max_y - min_y + 1

    panel_width = PANEL_PADDING * 2 + grid_width * CELL_SIZE
    panel_height = (
        TITLE_HEIGHT
        + PANEL_PADDING
        + grid_height * CELL_SIZE
        + PANEL_PADDING
    )

    levels: dict[int, list[DecodedVoxelRecord]] = defaultdict(list)
    for record in records:
        levels[record.chunk_z].append(record)

    z_values = sorted(levels)
    columns = min(PANELS_PER_ROW, len(z_values))
    rows = (len(z_values) + columns - 1) // columns

    canvas_width = (
        columns * panel_width
        + max(0, columns - 1) * PANEL_GAP
    )
    canvas_height = (
        rows * panel_height
        + max(0, rows - 1) * PANEL_GAP
    )

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{canvas_width}" height="{canvas_height}" '
            f'viewBox="0 0 {canvas_width} {canvas_height}">'
        ),
        "<style>",
        "text { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }",
        ".panel { fill: #0d1117; stroke: #30363d; stroke-width: 1; }",
        ".grid { stroke: #21262d; stroke-width: 1; }",
        ".chunk { fill: #2f81f7; }",
        ".title { fill: #f0f6fc; font-size: 16px; font-weight: 700; }",
        ".meta { fill: #8b949e; font-size: 11px; }",
        "</style>",
    ]

    for index, z in enumerate(z_values):
        column = index % columns
        row = index // columns
        origin_x = column * (panel_width + PANEL_GAP)
        origin_y = row * (panel_height + PANEL_GAP)

        parts.append(
            f'<rect class="panel" x="{origin_x}" y="{origin_y}" '
            f'width="{panel_width}" height="{panel_height}" rx="8" />'
        )

        count = len(levels[z])
        parts.append(
            f'<text class="title" x="{origin_x + PANEL_PADDING}" '
            f'y="{origin_y + 24}">'
            f'World {world_id} · Z={z} · {count} chunks'
            "</text>"
        )
        parts.append(
            f'<text class="meta" x="{origin_x + PANEL_PADDING}" '
            f'y="{origin_y + 40}">'
            f'X {min_x}..{max_x} · Y {min_y}..{max_y}'
            "</text>"
        )

        grid_x = origin_x + PANEL_PADDING
        grid_y = origin_y + TITLE_HEIGHT + PANEL_PADDING

        for gx in range(grid_width + 1):
            x = grid_x + gx * CELL_SIZE
            parts.append(
                f'<line class="grid" x1="{x}" y1="{grid_y}" '
                f'x2="{x}" y2="{grid_y + grid_height * CELL_SIZE}" />'
            )

        for gy in range(grid_height + 1):
            y = grid_y + gy * CELL_SIZE
            parts.append(
                f'<line class="grid" x1="{grid_x}" y1="{y}" '
                f'x2="{grid_x + grid_width * CELL_SIZE}" y2="{y}" />'
            )

        coordinates = Counter(
            (record.chunk_x, record.chunk_y)
            for record in levels[z]
        )

        for (chunk_x, chunk_y), duplicates in coordinates.items():
            pixel_x = grid_x + (chunk_x - min_x) * CELL_SIZE
            pixel_y = grid_y + (max_y - chunk_y) * CELL_SIZE

            opacity = min(1.0, 0.55 + 0.15 * duplicates)
            parts.append(
                f'<rect class="chunk" x="{pixel_x + 1}" '
                f'y="{pixel_y + 1}" '
                f'width="{CELL_SIZE - 2}" height="{CELL_SIZE - 2}" '
                f'opacity="{opacity:.2f}" />'
            )

    parts.append("</svg>")
    return "\n".join(parts)


def write_voxel_chunk_map(
    database: SaveDatabase,
    *,
    world_id: int,
    output: str | Path,
    limit: int = 5000,
) -> dict[str, object]:
    records, failures, scanned_records = decode_voxel_records(
        database,
        world_id=world_id,
        limit=limit,
    )

    if not records:
        raise ValueError(
            f"no decoded voxel chunk coordinates for world {world_id}"
        )

    if failures:
        raise ValueError(
            "not all voxel records could be decoded: "
            f"{dict(failures.most_common())}"
        )

    output_path = Path(output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_voxel_chunk_map_svg(
            records,
            world_id=world_id,
        ),
        encoding="utf-8",
    )

    min_x, max_x, min_y, max_y = _bounds(records)
    z_values = sorted({record.chunk_z for record in records})

    return {
        "world_id": world_id,
        "output": str(output_path),
        "scanned_records": scanned_records,
        "decoded_chunks": len(records),
        "bounds": {
            "min_x": min_x,
            "max_x": max_x,
            "min_y": min_y,
            "max_y": max_y,
            "min_z": min(z_values),
            "max_z": max(z_values),
        },
        "levels": z_values,
    }
