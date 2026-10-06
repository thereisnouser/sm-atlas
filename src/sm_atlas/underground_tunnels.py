from __future__ import annotations

from collections import Counter
from math import sqrt
from pathlib import Path

from .database import SaveDatabase
from .formats.lua_values import LuaValueError, LuaVec3, decode_lua_value
from .terrain_data import TERRAIN_SIGNAL_KEYS
from .terrain_data_probe import ScriptDataEnvelopeError, decode_script_data_envelope


def _load_terrain_table(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
) -> tuple[int, dict]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT rowid AS row_id, data
            FROM ScriptData
            WHERE worldId = ? AND data IS NOT NULL
            ORDER BY length(data) DESC, rowid
            LIMIT ?
            """,
            (world_id, limit),
        ).fetchall()

    best = None

    for row in rows:
        blob = row["data"]
        if not isinstance(blob, bytes):
            continue

        try:
            envelope = decode_script_data_envelope(blob)
            value = decode_lua_value(envelope.data)
        except (ScriptDataEnvelopeError, LuaValueError):
            continue

        if not isinstance(value, dict):
            continue

        string_keys = {key for key in value if isinstance(key, str)}
        score = len(string_keys.intersection(TERRAIN_SIGNAL_KEYS))
        if score == 0:
            continue

        candidate = (score, len(envelope.data), int(row["row_id"]), value)
        if best is None or candidate[:2] > best[:2]:
            best = candidate

    if best is None:
        raise ValueError(f"no terrain data found for world {world_id}")

    return best[2], best[3]


def _extract_tunnels(value: dict) -> list[dict]:
    raw_tunnels = value.get("tunnels")
    if not isinstance(raw_tunnels, dict):
        return []

    tunnels = []

    for tunnel_id, raw_tunnel in raw_tunnels.items():
        if not isinstance(tunnel_id, int) or not isinstance(raw_tunnel, dict):
            continue

        raw_positions = raw_tunnel.get("positions")
        if not isinstance(raw_positions, dict):
            continue

        points = []
        for index, point in raw_positions.items():
            if isinstance(index, int) and isinstance(point, LuaVec3):
                points.append((index, float(point.x), float(point.y), float(point.z)))

        points.sort(key=lambda item: item[0])
        if len(points) < 2:
            continue

        tunnel_type = raw_tunnel.get("tunnelType")
        if not isinstance(tunnel_type, str):
            tunnel_type = "Unknown"

        length = 0.0
        for left, right in zip(points, points[1:]):
            dx = right[1] - left[1]
            dy = right[2] - left[2]
            dz = right[3] - left[3]
            length += sqrt(dx * dx + dy * dy + dz * dz)

        tunnels.append(
            {
                "id": tunnel_id,
                "type": tunnel_type,
                "length": length,
                "points": [(x, y, z) for _, x, y, z in points],
            }
        )

    tunnels.sort(key=lambda tunnel: tunnel["id"])
    return tunnels


def summarize_underground_tunnels(
    database: SaveDatabase,
    *,
    world_id: int,
    limit: int = 5000,
) -> dict[str, object]:
    row_id, value = _load_terrain_table(
        database,
        world_id=world_id,
        limit=limit,
    )
    tunnels = _extract_tunnels(value)

    points = [
        point
        for tunnel in tunnels
        for point in tunnel["points"]
    ]
    type_counts = Counter(tunnel["type"] for tunnel in tunnels)

    data = value.get("data")
    depth = data.get("depth") if isinstance(data, dict) else None
    world_path = data.get("worldPath") if isinstance(data, dict) else None

    result = {
        "world_id": world_id,
        "row_id": row_id,
        "seed": value.get("seed"),
        "depth": depth,
        "world_path": world_path,
        "tunnels": len(tunnels),
        "points": len(points),
        "total_length": round(sum(t["length"] for t in tunnels), 3),
        "tunnel_types": dict(type_counts.most_common()),
    }

    if points:
        result["geometry_bounds"] = {
            "min_x": min(p[0] for p in points),
            "max_x": max(p[0] for p in points),
            "min_y": min(p[1] for p in points),
            "max_y": max(p[1] for p in points),
            "min_z": min(p[2] for p in points),
            "max_z": max(p[2] for p in points),
        }

    return result


def write_underground_tunnel_map(
    database: SaveDatabase,
    *,
    world_id: int,
    output: str | Path,
    limit: int = 5000,
) -> dict[str, object]:
    row_id, value = _load_terrain_table(
        database,
        world_id=world_id,
        limit=limit,
    )
    tunnels = _extract_tunnels(value)
    if not tunnels:
        raise ValueError(f"no tunnels found for world {world_id}")

    points = [p for tunnel in tunnels for p in tunnel["points"]]
    min_x = min(p[0] for p in points)
    max_x = max(p[0] for p in points)
    min_y = min(p[1] for p in points)
    max_y = max(p[1] for p in points)
    min_z = min(p[2] for p in points)
    max_z = max(p[2] for p in points)

    width = 1600
    height = 1200
    margin = 70
    legend_width = 300
    header = 100
    map_width = width - 2 * margin - legend_width
    map_height = height - header - 2 * margin
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    scale = min(map_width / span_x, map_height / span_y)

    draw_width = span_x * scale
    draw_height = span_y * scale
    origin_x = margin + (map_width - draw_width) / 2
    origin_y = header + margin + (map_height - draw_height) / 2

    tunnel_types = sorted({tunnel["type"] for tunnel in tunnels})
    palette = [
        "#58a6ff", "#f2cc60", "#7ee787", "#ff7b72", "#d2a8ff",
        "#ffa657", "#39c5cf", "#db61a2", "#a5d6ff", "#c9d1d9",
    ]
    colours = {
        tunnel_type: palette[index % len(palette)]
        for index, tunnel_type in enumerate(tunnel_types)
    }
    counts = Counter(tunnel["type"] for tunnel in tunnels)

    def sx(x: float) -> float:
        return origin_x + (x - min_x) * scale

    def sy(y: float) -> float:
        return origin_y + (max_y - y) * scale

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0d1117"/>',
        '<style>text{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.title{fill:#f0f6fc;font-size:24px;font-weight:700}.meta{fill:#8b949e;font-size:13px}.legend{fill:#c9d1d9;font-size:13px}</style>',
        f'<text class="title" x="{margin}" y="40">World {world_id} · Underground tunnels</text>',
        f'<text class="meta" x="{margin}" y="66">{len(tunnels)} tunnels · X {min_x:.1f}..{max_x:.1f} · Y {min_y:.1f}..{max_y:.1f} · Z {min_z:.1f}..{max_z:.1f}</text>',
        f'<rect x="{origin_x - 12:.2f}" y="{origin_y - 12:.2f}" width="{draw_width + 24:.2f}" height="{draw_height + 24:.2f}" rx="8" fill="#161b22" stroke="#30363d"/>',
    ]

    z_span = max(max_z - min_z, 1.0)

    for tunnel in tunnels:
        coords = " ".join(
            f"{sx(x):.2f},{sy(y):.2f}"
            for x, y, _ in tunnel["points"]
        )
        avg_z = sum(p[2] for p in tunnel["points"]) / len(tunnel["points"])
        opacity = 0.55 + 0.45 * ((avg_z - min_z) / z_span)
        colour = colours[tunnel["type"]]
        parts.append(
            f'<polyline points="{coords}" fill="none" stroke="{colour}" '
            f'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" '
            f'opacity="{opacity:.3f}" data-tunnel-id="{tunnel["id"]}" '
            f'data-tunnel-type="{tunnel["type"]}"/>'
        )

    legend_x = width - legend_width + 28
    parts.append(f'<text class="title" x="{legend_x}" y="{header + margin}">Tunnel types</text>')

    for index, tunnel_type in enumerate(tunnel_types):
        y = header + margin + 34 + index * 30
        colour = colours[tunnel_type]
        parts.append(
            f'<line x1="{legend_x}" y1="{y - 5}" x2="{legend_x + 28}" y2="{y - 5}" '
            f'stroke="{colour}" stroke-width="5" stroke-linecap="round"/>'
        )
        parts.append(
            f'<text class="legend" x="{legend_x + 40}" y="{y}">{tunnel_type} ({counts[tunnel_type]})</text>'
        )

    parts.append(f'<text class="meta" x="{legend_x}" y="{height - margin}">Opacity follows average Z</text>')
    parts.append("</svg>")

    output_path = Path(output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(parts), encoding="utf-8")

    result = summarize_underground_tunnels(
        database,
        world_id=world_id,
        limit=limit,
    )
    result["row_id"] = row_id
    result["output"] = str(output_path)
    return result
