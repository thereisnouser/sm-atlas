from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from html import escape
from pathlib import Path

from .database import SaveDatabase
from .underground_features import (
    UndergroundPiece,
    UndergroundSpawner,
    extract_caves,
    extract_pockets,
    extract_spawners,
    summarize_pieces,
    summarize_spawners,
)
from .underground_routes import TransitRoute, find_transit_route
from .underground_tunnels import (
    _extract_tunnels,
    _load_terrain_table,
    summarize_underground_tunnels,
)

CANVAS_WIDTH = 1800
CANVAS_HEIGHT = 1250
MARGIN = 70
HEADER_HEIGHT = 110
LEGEND_WIDTH = 340

TUNNEL_COLOURS = {
    "TtVeinT4": "#58a6ff",
    "TtVeinRich": "#f2cc60",
    "TtVeinSparkstone": "#d2a8ff",
    "TtDefault": "#8b949e",
    "MainVein": "#ffa657",
    "CrossVein": "#7ee787",
}

FALLBACK_TUNNEL_COLOURS = (
    "#39c5cf",
    "#ff7b72",
    "#db61a2",
    "#a5d6ff",
    "#c9d1d9",
)


@dataclass(frozen=True)
class UndergroundRouteOverlay:
    title: str
    tunnel_ids: tuple[int, ...]
    contact_segments: tuple[
        tuple[
            tuple[float, float, float],
            tuple[float, float, float],
        ],
        ...,
    ]
    start_point: tuple[float, float, float]
    target_point: tuple[float, float, float]
    target_tunnel_id: int | None = None


def _piece_bounds(
    pieces: list[UndergroundPiece],
) -> list[tuple[float, float, float, float, float, float]]:
    return [
        (
            piece.x,
            piece.max_x,
            piece.y,
            piece.max_y,
            piece.z,
            piece.max_z,
        )
        for piece in pieces
    ]


def _geometry_bounds(
    tunnels: list[dict],
    caves: list[UndergroundPiece],
    pockets: list[UndergroundPiece],
    spawners: list[UndergroundSpawner] | None = None,
) -> dict[str, float]:
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []

    for tunnel in tunnels:
        for x, y, z in tunnel["points"]:
            xs.append(x)
            ys.append(y)
            zs.append(z)

    for piece in caves + pockets:
        xs.extend((piece.x, piece.max_x))
        ys.extend((piece.y, piece.max_y))
        zs.extend((piece.z, piece.max_z))

    for spawner in spawners or []:
        xs.append(spawner.x)
        ys.append(spawner.y)
        zs.append(spawner.z)

    if not xs:
        raise ValueError("no underground geometry found")

    return {
        "min_x": min(xs),
        "max_x": max(xs),
        "min_y": min(ys),
        "max_y": max(ys),
        "min_z": min(zs),
        "max_z": max(zs),
    }


def summarize_underground_world(
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
    caves = extract_caves(value)
    pockets = extract_pockets(value)
    spawners = extract_spawners(value)

    tunnel_summary = summarize_underground_tunnels(
        database,
        world_id=world_id,
        limit=limit,
    )

    return {
        **tunnel_summary,
        "row_id": row_id,
        "caves": summarize_pieces(caves),
        "pockets": summarize_pieces(pockets),
        "spawners": summarize_spawners(spawners),
        "combined_geometry_bounds": _geometry_bounds(
            tunnels,
            caves,
            pockets,
            spawners,
        ),
    }


def _tunnel_colour_map(tunnels: list[dict]) -> dict[str, str]:
    tunnel_types = sorted({tunnel["type"] for tunnel in tunnels})
    colours: dict[str, str] = {}
    fallback_index = 0

    for tunnel_type in tunnel_types:
        colour = TUNNEL_COLOURS.get(tunnel_type)
        if colour is None:
            colour = FALLBACK_TUNNEL_COLOURS[
                fallback_index % len(FALLBACK_TUNNEL_COLOURS)
            ]
            fallback_index += 1
        colours[tunnel_type] = colour

    return colours


def render_underground_map_svg(
    *,
    world_id: int,
    tunnels: list[dict],
    caves: list[UndergroundPiece],
    pockets: list[UndergroundPiece],
    spawners: list[UndergroundSpawner],
    route_overlay: UndergroundRouteOverlay | None = None,
) -> str:
    bounds = _geometry_bounds(tunnels, caves, pockets, spawners)

    min_x = bounds["min_x"]
    max_x = bounds["max_x"]
    min_y = bounds["min_y"]
    max_y = bounds["max_y"]
    min_z = bounds["min_z"]
    max_z = bounds["max_z"]

    world_width = max(max_x - min_x, 1.0)
    world_height = max(max_y - min_y, 1.0)

    map_width = CANVAS_WIDTH - MARGIN * 2 - LEGEND_WIDTH
    map_height = CANVAS_HEIGHT - HEADER_HEIGHT - MARGIN * 2
    scale = min(
        map_width / world_width,
        map_height / world_height,
    )

    draw_width = world_width * scale
    draw_height = world_height * scale
    map_x = MARGIN + (map_width - draw_width) / 2
    map_y = (
        HEADER_HEIGHT
        + MARGIN
        + (map_height - draw_height) / 2
    )

    def sx(x: float) -> float:
        return map_x + (x - min_x) * scale

    def sy(y: float) -> float:
        return map_y + (max_y - y) * scale

    z_span = max(max_z - min_z, 1.0)

    def z_ratio(z: float) -> float:
        return (z - min_z) / z_span

    tunnel_colours = _tunnel_colour_map(tunnels)
    tunnel_counts = Counter(tunnel["type"] for tunnel in tunnels)

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}" '
            f'viewBox="0 0 {CANVAS_WIDTH} {CANVAS_HEIGHT}">'
        ),
        "<style>",
        "text{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}",
        ".title{fill:#f0f6fc;font-size:24px;font-weight:700}",
        ".meta{fill:#8b949e;font-size:13px}",
        ".legend{fill:#c9d1d9;font-size:13px}",
        ".section{fill:#f0f6fc;font-size:15px;font-weight:700}",
        ".tunnel{fill:none;stroke-linecap:round;stroke-linejoin:round}",
        ".cave{fill:#238636;stroke:#3fb950;stroke-width:1.5}",
        ".pocket{fill:#a371f7;stroke:#d2a8ff;stroke-width:1.2}",
        ".route-tunnel{fill:none;stroke:#ffffff;stroke-width:7;stroke-linecap:round;stroke-linejoin:round}",
        ".route-contact{fill:none;stroke:#58a6ff;stroke-width:5;stroke-dasharray:10 7;stroke-linecap:round}",
        ".route-target{fill:none;stroke:#ffdf5d;stroke-width:7;stroke-linecap:round;stroke-linejoin:round}",
        "</style>",
        (
            f'<rect x="0" y="0" width="{CANVAS_WIDTH}" '
            f'height="{CANVAS_HEIGHT}" fill="#0d1117"/>'
        ),
        (
            f'<text class="title" x="{MARGIN}" y="40">'
            f'World {world_id} · Underground'
            "</text>"
        ),
        (
            f'<text class="meta" x="{MARGIN}" y="66">'
            f'{len(tunnels)} tunnels · {len(caves)} caves · '
            f'{len(pockets)} pockets · {len(spawners)} spawners · '
            f'Z {min_z:.1f}..{max_z:.1f} m'
            "</text>"
        ),
        (
            f'<rect x="{map_x - 12:.2f}" y="{map_y - 12:.2f}" '
            f'width="{draw_width + 24:.2f}" '
            f'height="{draw_height + 24:.2f}" rx="8" '
            f'fill="#161b22" stroke="#30363d"/>'
        ),
    ]

    if route_overlay is not None:
        parts.append(
            f'<text class="meta" x="{MARGIN}" y="88">'
            f'Route: {escape(route_overlay.title)}'
            "</text>"
        )

    # Caves are large cell-sized placements; render them first as a faint
    # structural layer so the tunnel network remains readable on top.
    for index, cave in enumerate(caves, start=1):
        opacity = 0.08 + 0.12 * z_ratio(
            cave.z + cave.height / 2
        )
        x = sx(cave.x)
        y = sy(cave.max_y)
        width = cave.width * scale
        height = cave.depth * scale

        parts.append(
            f'<g data-feature="cave" data-index="{index}" '
            f'data-tile-index="{cave.tile_index}">'
            f'<title>Cave #{index} · tile {cave.tile_index} · '
            f'Z {cave.z:.0f}..{cave.max_z:.0f} m · '
            f'{cave.width:.0f}×{cave.depth:.0f} m</title>'
            f'<rect class="cave" x="{x:.2f}" y="{y:.2f}" '
            f'width="{width:.2f}" height="{height:.2f}" '
            f'opacity="{opacity:.3f}"/>'
            "</g>"
        )

    # Pockets are smaller chunk-granularity placements and are more useful as
    # explicit POI-like regions, so they get a stronger fill.
    for index, pocket in enumerate(pockets, start=1):
        opacity = 0.15 + 0.22 * z_ratio(
            pocket.z + pocket.height / 2
        )
        x = sx(pocket.x)
        y = sy(pocket.max_y)
        width = pocket.width * scale
        height = pocket.depth * scale

        uuid_text = (
            f" · {escape(pocket.tile_uuid)}"
            if pocket.tile_uuid
            else ""
        )
        parts.append(
            f'<g data-feature="pocket" data-index="{index}" '
            f'data-tile-index="{pocket.tile_index}">'
            f'<title>Pocket #{index} · tile {pocket.tile_index}'
            f'{uuid_text} · Z {pocket.z:.0f}..{pocket.max_z:.0f} m · '
            f'{pocket.width:.0f}×{pocket.depth:.0f} m</title>'
            f'<rect class="pocket" x="{x:.2f}" y="{y:.2f}" '
            f'width="{width:.2f}" height="{height:.2f}" '
            f'opacity="{opacity:.3f}"/>'
            "</g>"
        )

    for index, spawner in enumerate(spawners, start=1):
        x = sx(spawner.x)
        y = sy(spawner.y)
        opacity = 0.65 + 0.35 * z_ratio(spawner.z)
        tags = ", ".join(spawner.tags) if spawner.tags else "untagged"
        trigger = spawner.trigger_name or "unknown"
        radius = 4.0

        parts.append(
            f'<g data-feature="spawner" data-index="{index}">'
            f'<title>Spawner #{index} · {escape(tags)} · '
            f'trigger {escape(trigger)} · '
            f'XYZ {spawner.x:.1f}, {spawner.y:.1f}, {spawner.z:.1f} · '
            f'scale {spawner.scale_x:.0f}×{spawner.scale_y:.0f}×'
            f'{spawner.scale_z:.0f}</title>'
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" '
            f'fill="#f85149" stroke="#ff7b72" stroke-width="1.5" '
            f'opacity="{opacity:.3f}"/>'
            f'<line x1="{x - 6:.2f}" y1="{y:.2f}" '
            f'x2="{x + 6:.2f}" y2="{y:.2f}" '
            f'stroke="#ff7b72" stroke-width="1.2" '
            f'opacity="{opacity:.3f}"/>'
            f'<line x1="{x:.2f}" y1="{y - 6:.2f}" '
            f'x2="{x:.2f}" y2="{y + 6:.2f}" '
            f'stroke="#ff7b72" stroke-width="1.2" '
            f'opacity="{opacity:.3f}"/>'
            "</g>"
        )

    for tunnel in tunnels:
        coordinates = " ".join(
            f"{sx(x):.2f},{sy(y):.2f}"
            for x, y, _ in tunnel["points"]
        )
        average_z = sum(
            point[2]
            for point in tunnel["points"]
        ) / len(tunnel["points"])
        opacity = 0.60 + 0.40 * z_ratio(average_z)
        colour = tunnel_colours[tunnel["type"]]

        parts.append(
            f'<polyline class="tunnel" '
            f'points="{coordinates}" '
            f'stroke="{colour}" stroke-width="3.2" '
            f'opacity="{opacity:.3f}" '
            f'data-tunnel-id="{tunnel["id"]}" '
            f'data-tunnel-type="{escape(tunnel["type"])}">'
            f'<title>{escape(tunnel["type"])} · '
            f'Tunnel #{tunnel["id"]} · '
            f'{tunnel["length"]:.1f} m · '
            f'{len(tunnel["points"])} points</title>'
            "</polyline>"
        )

    if route_overlay is not None:
        tunnel_lookup = {
            int(tunnel["id"]): tunnel
            for tunnel in tunnels
        }

        for tunnel_id in route_overlay.tunnel_ids:
            tunnel = tunnel_lookup.get(tunnel_id)
            if tunnel is None:
                continue

            coordinates = " ".join(
                f"{sx(x):.2f},{sy(y):.2f}"
                for x, y, _ in tunnel["points"]
            )
            parts.append(
                f'<polyline class="route-tunnel" '
                f'points="{coordinates}" opacity="0.92" '
                f'data-feature="route-tunnel" '
                f'data-tunnel-id="{tunnel_id}">'
                f'<title>Route tunnel #{tunnel_id} · '
                f'{escape(tunnel["type"])} · '
                f'{tunnel["length"]:.1f} m</title>'
                "</polyline>"
            )

        for start, end in route_overlay.contact_segments:
            parts.append(
                f'<line class="route-contact" '
                f'x1="{sx(start[0]):.2f}" y1="{sy(start[1]):.2f}" '
                f'x2="{sx(end[0]):.2f}" y2="{sy(end[1]):.2f}" '
                f'data-feature="route-contact">'
                "<title>Candidate intra-tile/contact connector</title>"
                "</line>"
            )

        if route_overlay.target_tunnel_id is not None:
            tunnel = tunnel_lookup.get(
                route_overlay.target_tunnel_id
            )
            if tunnel is not None:
                coordinates = " ".join(
                    f"{sx(x):.2f},{sy(y):.2f}"
                    for x, y, _ in tunnel["points"]
                )
                parts.append(
                    f'<polyline class="route-target" '
                    f'points="{coordinates}" opacity="0.98" '
                    f'data-feature="route-target-tunnel" '
                    f'data-tunnel-id="{tunnel["id"]}">'
                    f'<title>Target tunnel #{tunnel["id"]} · '
                    f'{escape(tunnel["type"])} · '
                    f'{tunnel["length"]:.1f} m</title>'
                    "</polyline>"
                )

        start_x = sx(route_overlay.start_point[0])
        start_y = sy(route_overlay.start_point[1])
        target_x = sx(route_overlay.target_point[0])
        target_y = sy(route_overlay.target_point[1])

        parts.append(
            f'<g data-feature="route-start">'
            f'<circle cx="{start_x:.2f}" cy="{start_y:.2f}" r="9" '
            f'fill="#238636" stroke="#f0f6fc" stroke-width="2"/>'
            "<title>Route start · elevator</title>"
            "</g>"
        )
        parts.append(
            f'<g data-feature="route-target">'
            f'<circle cx="{target_x:.2f}" cy="{target_y:.2f}" r="9" '
            f'fill="#ffdf5d" stroke="#f0f6fc" stroke-width="2"/>'
            "<title>Route target entrance</title>"
            "</g>"
        )

    legend_x = CANVAS_WIDTH - LEGEND_WIDTH + 28
    legend_y = HEADER_HEIGHT + MARGIN

    parts.append(
        f'<text class="section" x="{legend_x}" y="{legend_y}">'
        "Features"
        "</text>"
    )
    parts.append(
        f'<rect x="{legend_x}" y="{legend_y + 18}" '
        f'width="24" height="14" fill="#238636" '
        f'stroke="#3fb950" opacity="0.35"/>'
    )
    parts.append(
        f'<text class="legend" x="{legend_x + 38}" '
        f'y="{legend_y + 30}">Caves ({len(caves)})</text>'
    )
    parts.append(
        f'<rect x="{legend_x}" y="{legend_y + 44}" '
        f'width="24" height="14" fill="#a371f7" '
        f'stroke="#d2a8ff" opacity="0.55"/>'
    )
    parts.append(
        f'<text class="legend" x="{legend_x + 38}" '
        f'y="{legend_y + 56}">Pockets ({len(pockets)})</text>'
    )
    parts.append(
        f'<circle cx="{legend_x + 12}" cy="{legend_y + 82}" '
        f'r="5" fill="#f85149" stroke="#ff7b72"/>'
    )
    parts.append(
        f'<text class="legend" x="{legend_x + 38}" '
        f'y="{legend_y + 87}">Spawners ({len(spawners)})</text>'
    )

    tunnel_legend_y = legend_y + 130
    parts.append(
        f'<text class="section" x="{legend_x}" '
        f'y="{tunnel_legend_y}">Tunnel types</text>'
    )

    for index, tunnel_type in enumerate(sorted(tunnel_colours)):
        y = tunnel_legend_y + 30 + index * 30
        colour = tunnel_colours[tunnel_type]
        parts.append(
            f'<line x1="{legend_x}" y1="{y - 5}" '
            f'x2="{legend_x + 28}" y2="{y - 5}" '
            f'stroke="{colour}" stroke-width="5" '
            f'stroke-linecap="round"/>'
        )
        parts.append(
            f'<text class="legend" x="{legend_x + 40}" y="{y}">'
            f'{escape(tunnel_type)} ({tunnel_counts[tunnel_type]})'
            "</text>"
        )

    parts.append(
        f'<text class="meta" x="{legend_x}" '
        f'y="{CANVAS_HEIGHT - MARGIN - 20}">'
        "Hover SVG geometry for details"
        "</text>"
    )
    parts.append(
        f'<text class="meta" x="{legend_x}" '
        f'y="{CANVAS_HEIGHT - MARGIN}">'
        "Opacity follows vertical position (Z)"
        "</text>"
    )
    parts.append("</svg>")

    return "\n".join(parts)


def _route_overlay(
    route: TransitRoute,
) -> UndergroundRouteOverlay:
    route_tunnel_ids = tuple(
        segment.tunnel_id
        for segment in route.segments
        if (
            segment.kind == "tunnel"
            and segment.tunnel_id is not None
        )
    )
    contact_segments = tuple(
        (
            segment.from_point,
            segment.to_point,
        )
        for segment in route.segments
        if (
            segment.kind != "tunnel"
            and segment.from_point != segment.to_point
        )
    )

    if route.target_tunnel_id is not None:
        title = (
            f"Elevator → {route.target_tunnel_type} "
            f"#{route.target_tunnel_id} entrance"
        )
    else:
        title = (
            f"Elevator → {route.target_kind} "
            f"{route.target_value}"
        )

    start_point = (
        route.start_point
        if route.start_point is not None
        else (0.0, 0.0, 0.0)
    )
    target_point = (
        route.target_point
        if route.target_point is not None
        else start_point
    )

    return UndergroundRouteOverlay(
        title=title,
        tunnel_ids=tuple(
            tunnel_id
            for tunnel_id in route_tunnel_ids
            if tunnel_id != route.target_tunnel_id
        ),
        contact_segments=contact_segments,
        start_point=start_point,
        target_point=target_point,
        target_tunnel_id=route.target_tunnel_id,
    )


def write_underground_route_map(
    database: SaveDatabase,
    *,
    world_id: int,
    output: str | Path,
    limit: int = 5000,
    include_vertical_contacts: bool = False,
    target_node: int | None = None,
    target_tag: str | None = None,
    target_tunnel_type: str | None = None,
) -> dict[str, object]:
    route, lookup = find_transit_route(
        database,
        world_id=world_id,
        limit=limit,
        include_vertical_contacts=include_vertical_contacts,
        target_node=target_node,
        target_tag=target_tag,
        target_tunnel_type=target_tunnel_type,
    )
    row_id, value = _load_terrain_table(
        database,
        world_id=world_id,
        limit=limit,
    )
    tunnels = _extract_tunnels(value)
    caves = extract_caves(value)
    pockets = extract_pockets(value)
    spawners = extract_spawners(value)
    overlay = _route_overlay(route)

    output_path = Path(output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_underground_map_svg(
            world_id=world_id,
            tunnels=tunnels,
            caves=caves,
            pockets=pockets,
            spawners=spawners,
            route_overlay=overlay,
        ),
        encoding="utf-8",
    )

    result = route.to_dict(lookup)
    result["row_id"] = row_id
    result["output"] = str(output_path)
    return result


def write_underground_map(
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
    caves = extract_caves(value)
    pockets = extract_pockets(value)
    spawners = extract_spawners(value)

    output_path = Path(output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_underground_map_svg(
            world_id=world_id,
            tunnels=tunnels,
            caves=caves,
            pockets=pockets,
            spawners=spawners,
        ),
        encoding="utf-8",
    )

    summary = summarize_underground_world(
        database,
        world_id=world_id,
        limit=limit,
    )
    summary["row_id"] = row_id
    summary["output"] = str(output_path)
    return summary