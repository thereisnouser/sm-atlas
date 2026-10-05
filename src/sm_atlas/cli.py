from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from .database import InvalidSaveFile, SaveDatabase


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sm-atlas",
        description="Inspect Scrap Mechanic save files.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

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
    print(f"Scrap Mechanic signal: {result['sm_signal']}")
    print()

    for table, count in result["tables"].items():
        marker = "*" if table in result["known_tables"] else " "
        print(f"{marker} {table}: {count}")

    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "inspect":
        raise SystemExit(run_inspect(args.save, args.json))


if __name__ == "__main__":
    main()
