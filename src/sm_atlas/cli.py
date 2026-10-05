from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from .database import InvalidSaveFile, SaveDatabase
from .discovery import find_survival_saves


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


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "saves":
        raise SystemExit(run_saves(args.root, args.json))

    if args.command == "inspect":
        raise SystemExit(run_inspect(args.save, args.json))


if __name__ == "__main__":
    main()
