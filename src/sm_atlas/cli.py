from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from .database import InvalidSaveFile, SaveDatabase
from .discovery import find_survival_saves
from .terrain import summarize_voxel_terrain
from .terrain_chunks import summarize_voxel_chunks
from .terrain_decode import probe_decompressed_voxel_terrain
from .terrain_layout import scan_voxel_terrain_layout
from .terrain_map import write_voxel_chunk_map
from .terrain_payload import probe_voxel_payloads
from .terrain_probe import probe_voxel_terrain
from .terrain_structure import probe_voxel_terrain_structure
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

    structure_parser = subparsers.add_parser(
        "terrain-structure",
        help="Probe VoxelTerrain record structure and candidate chunk coordinates.",
    )
    structure_parser.add_argument("save", type=Path)
    structure_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    structure_parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum records to scan (1-5000).",
    )
    structure_parser.add_argument(
        "--examples",
        type=int,
        default=30,
        help="Maximum example records to include (0-200).",
    )
    structure_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    layout_parser = subparsers.add_parser(
        "terrain-layout",
        help="Scan VoxelTerrain blobs for coordinate layout candidates.",
    )
    layout_parser.add_argument("save", type=Path)
    layout_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    layout_parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum records to scan (1-5000).",
    )
    layout_parser.add_argument(
        "--min-offset",
        type=int,
        default=8,
        help="Minimum offset relative to the embedded record ID.",
    )
    layout_parser.add_argument(
        "--max-offset",
        type=int,
        default=64,
        help="Maximum offset relative to the embedded record ID.",
    )
    layout_parser.add_argument(
        "--top",
        type=int,
        default=25,
        help="Number of highest-scoring layouts to show.",
    )
    layout_parser.add_argument(
        "--z-limit",
        type=int,
        default=128,
        help="Absolute Z value considered plausible.",
    )
    layout_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    chunks_parser = subparsers.add_parser(
        "terrain-chunks",
        help="Decode confident voxel chunk coordinates from save records.",
    )
    chunks_parser.add_argument("save", type=Path)
    chunks_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    chunks_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum records to scan (1-5000).",
    )
    chunks_parser.add_argument(
        "--examples",
        type=int,
        default=25,
        help="Maximum decoded records to include (0-200).",
    )
    chunks_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    map_parser = subparsers.add_parser(
        "terrain-map",
        help="Render decoded voxel chunk occupancy as SVG slices.",
    )
    map_parser.add_argument("save", type=Path)
    map_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to render.",
    )
    map_parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="SVG output path.",
    )
    map_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum records to scan (1-5000).",
    )

    decode_parser = subparsers.add_parser(
        "terrain-decode",
        help="Decompress VoxelTerrain records and validate voxel chunk layout.",
    )
    decode_parser.add_argument("save", type=Path)
    decode_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    decode_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum records to scan (1-5000).",
    )
    decode_parser.add_argument(
        "--examples",
        type=int,
        default=10,
        help="Maximum decoded records to include (0-100).",
    )
    decode_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    payload_parser = subparsers.add_parser(
        "terrain-payload",
        help="Inspect the variable payload inside decompressed voxel records.",
    )
    payload_parser.add_argument("save", type=Path)
    payload_parser.add_argument(
        "--world",
        type=int,
        required=True,
        help="World ID to inspect.",
    )
    payload_parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum records to scan (1-5000).",
    )
    payload_parser.add_argument(
        "--max-offset",
        type=int,
        default=16,
        help="Maximum payload offset to test for an inner LZ4 block.",
    )
    payload_parser.add_argument(
        "--examples",
        type=int,
        default=20,
        help="Maximum example payloads to include (0-100).",
    )
    payload_parser.add_argument(
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


def run_terrain_structure(
    save: Path,
    world_id: int,
    limit: int,
    examples: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = probe_voxel_terrain_structure(
            database,
            world_id=world_id,
            limit=limit,
            examples=examples,
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
    print(f"Marker matches: {result['marker_matches']}")
    print(f"ID matches: {result['id_matches']}")
    print(f"Sentinel matches: {result['sentinel_matches']}")
    print(
        "Direct coordinate candidates: "
        f"{result['direct_coordinate_candidates']}"
    )
    print(f"Exact cell matches: {result['exact_cell_matches']}")
    print(f"Boundary cell matches: {result['boundary_cell_matches']}")
    print(f"Marker offsets: {result['marker_offsets']}")
    print(f"ID offsets: {result['id_offsets']}")
    print(f"Prefix signatures: {result['prefix_signatures']}")
    print(f"Candidate Z range: {result['candidate_z_range']}")

    return 0


def run_terrain_layout(
    save: Path,
    world_id: int,
    limit: int,
    min_offset: int,
    max_offset: int,
    top: int,
    z_limit: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = scan_voxel_terrain_layout(
            database,
            world_id=world_id,
            limit=limit,
            min_relative_offset=min_offset,
            max_relative_offset=max_offset,
            top=top,
            z_limit=z_limit,
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
    print(f"Records with embedded ID: {result['records_with_id']}")
    print(f"Marker offsets: {result['marker_offsets']}")
    print()
    print("Top layouts:")

    for score in result["top_layouts"]:
        print(
            f"  {score['endian']:>6} "
            f"{score['axis_order']:>3} "
            f"factor={score['factor']} "
            f"offset=+{score['relative_offset']}: "
            f"xy={score['exact_xy_matches']} "
            f"z={score['plausible_z_matches']} "
            f"m1={score['marker_1_matches']} "
            f"m2={score['marker_2_matches']} "
            f"zrange={score['z_range']}"
        )

    print()
    print("Big-endian/ZYX/factor=4 offset peaks:")

    for score in result["big_zyx_factor4_offsets"]:
        print(
            f"  offset=+{score['relative_offset']}: "
            f"xy={score['exact_xy_matches']} "
            f"z={score['plausible_z_matches']} "
            f"m1={score['marker_1_matches']} "
            f"m2={score['marker_2_matches']} "
            f"zrange={score['z_range']}"
        )

    return 0


def run_terrain_chunks(
    save: Path,
    world_id: int,
    limit: int,
    examples: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = summarize_voxel_chunks(
            database,
            world_id=world_id,
            limit=limit,
            examples=examples,
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
    print(f"Decoded records: {result['decoded_records']}")
    print(f"Unresolved records: {result['unresolved_records']}")
    print(f"Decode ratio: {result['decode_ratio']:.1%}")
    print(
        "Unique chunk coordinates: "
        f"{result['unique_chunk_coordinates']}"
    )
    print(
        "Duplicate coordinate records: "
        f"{result['duplicate_coordinate_records']}"
    )
    print(
        "Coordinates with duplicates: "
        f"{result['duplicate_coordinates']}"
    )
    print(f"Failures: {result['failures']}")
    print(f"Chunk bounds: {result['chunk_bounds']}")
    print(f"Z histogram: {result['z_histogram']}")
    print(f"Payload sizes: {result['payload_size_histogram']}")
    print(f"Payload prefixes: {result['payload_prefixes']}")

    return 0


def run_terrain_map(
    save: Path,
    world_id: int,
    output: Path,
    limit: int,
) -> int:
    database = SaveDatabase(save)

    try:
        result = write_voxel_chunk_map(
            database,
            world_id=world_id,
            output=output,
            limit=limit,
        )
    except (
        FileNotFoundError,
        InvalidSaveFile,
        sqlite3.DatabaseError,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}")
        return 1

    print(f"World: {result['world_id']}")
    print(f"Decoded chunks: {result['decoded_chunks']}")
    print(f"Bounds: {result['bounds']}")
    print(f"Levels: {result['levels']}")
    print(f"SVG: {result['output']}")

    return 0


def run_terrain_decode(
    save: Path,
    world_id: int,
    limit: int,
    examples: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = probe_decompressed_voxel_terrain(
            database,
            world_id=world_id,
            limit=limit,
            examples=examples,
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
    print(f"Decoded records: {result['decoded_records']}")
    print(f"Decode ratio: {result['decode_ratio']:.1%}")
    print(f"Failures: {result['failures']}")
    print(
        "Decompressed sizes: "
        f"{result['decompressed_size_histogram']}"
    )
    print(
        "Payload sizes: "
        f"{result['payload_size_histogram']}"
    )
    print(
        "Exact 17^3 voxel payloads: "
        f"{result['exact_voxel_payload_records']}"
    )
    print(
        "Unique chunk coordinates: "
        f"{result['unique_chunk_coordinates']}"
    )
    print(
        "Duplicate coordinate records: "
        f"{result['duplicate_coordinate_records']}"
    )
    print(f"Chunk bounds: {result['chunk_bounds']}")

    return 0


def run_terrain_payload(
    save: Path,
    world_id: int,
    limit: int,
    max_offset: int,
    examples: int,
    as_json: bool,
) -> int:
    database = SaveDatabase(save)

    try:
        result = probe_voxel_payloads(
            database,
            world_id=world_id,
            limit=limit,
            max_offset=max_offset,
            examples=examples,
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
    print(f"Decoded records: {result['decoded_records']}")
    print(f"Decode failures: {result['decode_failures']}")
    print(f"Payload size range: {result['payload_size_range']}")
    print(f"Four-byte records: {result['four_byte_records']}")
    print(f"Four-byte values: {result['four_byte_values']}")
    print(f"First byte histogram: {result['first_byte_histogram']}")
    print(f"First u16 BE histogram: {result['first_u16_be_histogram']}")
    print(f"Frame: {result['frame']}")
    print(f"Format groups: {result['format_groups']}")
    print(f"Payload prefixes: {result['payload_prefixes']}")
    print(f"Inner LZ4 matches: {result['inner_lz4_matches']}")
    print(
        "Inner LZ4 offsets: "
        f"{result['inner_lz4_offset_histogram']}"
    )
    print(
        "Exact inner LZ4 records: "
        f"{result['exact_inner_lz4_records']}"
    )

    if result["examples"]:
        print()
        print("Payload examples:")

        for example in result["examples"]:
            chunk = example["chunk"]
            print(
                f"  id={example['id']} "
                f"chunk=({chunk['x']},{chunk['y']},{chunk['z']}) "
                f"size={example['payload_size']} "
                f"prefix={example['payload_prefix_hex']}"
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

    if args.command == "terrain-structure":
        raise SystemExit(
            run_terrain_structure(
                args.save,
                args.world,
                args.limit,
                args.examples,
                args.json,
            )
        )

    if args.command == "terrain-layout":
        raise SystemExit(
            run_terrain_layout(
                args.save,
                args.world,
                args.limit,
                args.min_offset,
                args.max_offset,
                args.top,
                args.z_limit,
                args.json,
            )
        )

    if args.command == "terrain-chunks":
        raise SystemExit(
            run_terrain_chunks(
                args.save,
                args.world,
                args.limit,
                args.examples,
                args.json,
            )
        )

    if args.command == "terrain-map":
        raise SystemExit(
            run_terrain_map(
                args.save,
                args.world,
                args.output,
                args.limit,
            )
        )

    if args.command == "terrain-decode":
        raise SystemExit(
            run_terrain_decode(
                args.save,
                args.world,
                args.limit,
                args.examples,
                args.json,
            )
        )

    if args.command == "terrain-payload":
        raise SystemExit(
            run_terrain_payload(
                args.save,
                args.world,
                args.limit,
                args.max_offset,
                args.examples,
                args.json,
            )
        )

    if args.command == "schema":
        raise SystemExit(run_schema(args.save, args.table))

    if args.command == "sample":
        raise SystemExit(run_sample(args.save, args.table, args.limit))


if __name__ == "__main__":
    main()