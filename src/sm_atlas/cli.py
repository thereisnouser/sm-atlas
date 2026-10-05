from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from .database import InvalidSaveFile, SaveDatabase
from .discovery import find_survival_saves
from .terrain import summarize_voxel_terrain
from .terrain_probe import probe_voxel_terrain
from .world_graph import build_world_graph
from .worlds import WorldDataError, discover_worlds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sm-atlas",
        description="Inspect Scrap Mechanic save files.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    saves_parser = subparsers.add_parser(
        "saves",
        help="Find local Survival saves.",
    )
    saves_parser.add_argument(
        "--root",
        type=Path,
        help="Override the Scrap Mechanic User directory.",
    )
    saves_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect a save database.",
    )
    inspect_parser.add_argument("save", type=Path)
    inspect_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    worlds_parser = subparsers.add_parser(
        "worlds",
        help="Discover worlds stored in GenericData.",
    )
    worlds_parser.add_argument("save", type=Path)
    worlds_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    graph_parser = subparsers.add_parser(
        "graph",
        help="Show portal connections between worlds.",
    )
    graph_parser.add_argument("save", type=Path)
    graph_parser.add_argument(
        "--underground",
        action="store_true",
        help="Only show connections touching an Underground world.",
    )
    graph_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    terrain_parser = subparsers.add_parser(
        "terrain",
        help="Summarize saved voxel terrain by world.",
    )
    terrain_parser.add_argument("save", type=Path)
    terrain_parser.add_argument(
        "--underground",
        action="store_true",
        help="Only show Underground worlds.",
    )
    terrain_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    probe_parser = subparsers.add_parser(
        "terrain-probe",
        help="Probe VoxelTerrain blobs for embedded LZ4 voxel chunks.",
    )
    probe_parser.add_argument("save", type=Path)
    probe_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    probe_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum records to scan (1-5000).",
    )
    probe_parser.add_argument(
        "--max-offset",
        type=int,
        default=96,
        help="Maximum blob offset to test for an LZ4 block.",
    )
    probe_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    schema_parser = subparsers.add_parser(
        "schema",
        help="Show columns for a save table.",
    )
    schema_parser.add_argument("save", type=Path)
    schema_parser.add_argument("table")

    sample_parser = subparsers.add_parser(
        "sample",
        help="Show safe sample rows from a save table.",
    )
    sample_parser.add_argument("save", type=Path)
    sample_parser.add_argument("table")
    sample_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of rows to show (1-100).",
    )

    return parser


def run_saves(root: Path | None, as_json: bool) -> int:
    saves = find_survival_saves(root)

    if as_json:
        print(
            json.dumps(
                [save.to_dict() for save in saves],
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    if not saves:
        print("No Scrap Mechanic Survival saves found.")
        return 0

    for index, save in enumerate(saves, start=1):
        size_mb = save.size_bytes / (1024 * 1024)
        print(
            f"[{index}] {save.path.stem} "
            f"({size_mb:.1f} MB)\n    {save.path}"
        )

    return 0


def run_inspect(save: Path, as_json: bool) -> int:
    database = SaveDatabase(save)

    try:
        result = database.inspect()
    except (FileNotFoundError, InvalidSaveFile, sqlite3.DatabaseError) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"Save: {result['path']}")
    print(f"Size: {result['size_bytes']} bytes")
    print(f"SQLite user_version: {result['user_version']}")
    print(f"Scrap Mechanic signal: {result['sm_signal']}")
    print()

    for table, count in result["tables"].items():
        marker = "*" if table in result["known_tables"] else " "
        print(f"{marker} {table}: {count}")

    return 0


def run_worlds(save: Path, as_json: bool) -> int:
    database = SaveDatabase(save)

    try:
        worlds = discover_worlds(database)
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        WorldDataError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(
            json.dumps(
                [world.to_dict() for world in worlds],
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    if not worlds:
        print("No world definitions found.")
        return 0

    for world in worlds:
        extra = f" depth={world.depth}" if world.depth is not None else ""
        print(
            f"[{world.world_id}] {world.label} "
            f"({world.kind}{extra})\n"
            f"    class: {world.classname}\n"
            f"    seed: {world.seed}\n"
            f"    file: {world.filename}"
        )

    return 0


def run_graph(
    save: Path,
    underground_only: bool,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        graph = build_world_graph(
            database,
            underground_only=underground_only,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        WorldDataError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(graph.to_dict(), indent=2, ensure_ascii=False))
        return 0

    if not graph.connections:
        print("No matching portal connections found.")
        return 0

    for connection in graph.connections:
        print(
            f"[portal {connection.portal_id}] "
            f"{connection.a.label} #{connection.a.world_id} "
            f"({connection.a.x}, {connection.a.y}) "
            f"-> "
            f"{connection.b.label} #{connection.b.world_id} "
            f"({connection.b.x}, {connection.b.y})"
        )

    return 0


def run_terrain(
    save: Path,
    underground_only: bool,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        summaries = summarize_voxel_terrain(
            database,
            underground_only=underground_only,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        WorldDataError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(
            json.dumps(
                [summary.to_dict() for summary in summaries],
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    if not summaries:
        print("No matching voxel terrain records found.")
        return 0

    for summary in summaries:
        print(
            f"[{summary.world_id}] {summary.label} "
            f"({summary.kind})\n"
            f"    records: {summary.records}\n"
            f"    unique coordinates: {summary.unique_coordinates}\n"
            f"    bounds: x={summary.min_x}..{summary.max_x}, "
            f"y={summary.min_y}..{summary.max_y}\n"
            f"    blob bytes: {summary.total_blob_bytes}"
        )

    return 0


def run_terrain_probe(
    save: Path,
    world_id: int,
    limit: int,
    max_offset: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = probe_voxel_terrain(
            database,
            world_id=world_id,
            limit=limit,
            max_offset=max_offset,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"World: {result['world_id']}")
    print(f"Scanned records: {result['scanned_records']}")
    print(f"LZ4 matches: {result['matched_records']}")
    print(f"Offset histogram: {result['offset_histogram']}")

    for record in result["records"]:
        if not record["lz4_candidates"]:
            continue

        print(
            f"[{record['id']}] ({record['x']}, {record['y']}) "
            f"{record['blob_size']} bytes -> "
            f"{record['lz4_candidates']}"
        )

    return 0


def run_schema(save: Path, table: str) -> int:
    database = SaveDatabase(save)

    try:
        result = database.schema(table)
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        KeyError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def run_sample(save: Path, table: str, limit: int) -> int:
    database = SaveDatabase(save)

    try:
        result = database.sample(table, limit)
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        KeyError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "saves":
        raise SystemExit(run_saves(args.root, args.json))

    if args.command == "inspect":
        raise SystemExit(run_inspect(args.save, args.json))

    if args.command == "worlds":
        raise SystemExit(run_worlds(args.save, args.json))

    if args.command == "graph":
        raise SystemExit(
            run_graph(
                args.save,
                args.underground,
                args.json,
            )
        )

    if args.command == "terrain":
        raise SystemExit(
            run_terrain(
                args.save,
                args.underground,
                args.json,
            )
        )

    if args.command == "terrain-probe":
        raise SystemExit(
            run_terrain_probe(
                args.save,
                args.world,
                args.limit,
                args.max_offset,
                args.json,
            )
        )

    if args.command == "schema":
        raise SystemExit(run_schema(args.save, args.table))

    if args.command == "sample":
        raise SystemExit(run_sample(args.save, args.table, args.limit))


if __name__ == "__main__":
    main()
