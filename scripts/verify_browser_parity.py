"""Compare Python research decoding with actual browser modules on a local save.

Developer workflow only. Never upload or commit the input save or its output.
Requires the Python package, Node.js 22+ and web/node_modules/sql.js.

    python scripts/verify_browser_parity.py /path/to/save.db
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

from sm_atlas.database import SaveDatabase
from sm_atlas.underground_features import extract_caves, extract_pockets
from sm_atlas.underground_layout import (
    _dimensions_from_name,
    reconstruct_logical_structures,
)
from sm_atlas.underground_pockets import reconstruct_logical_pockets
from sm_atlas.underground_tunnels import _extract_tunnels, _load_terrain_table
from sm_atlas.worlds import discover_worlds

ROOT = Path(__file__).resolve().parents[1]


def _tunnel_digest(tunnels: list[dict]) -> str:
    digest = hashlib.sha256()
    for tunnel in sorted(tunnels, key=lambda t: t["id"]):
        points = tunnel["points"]
        digest.update(
            f'{tunnel["id"]}:{tunnel["type"]}:{len(points)}\n'.encode()
        )
        for point in points:
            digest.update(struct.pack(">fff", *point))
    return digest.hexdigest()


def _placement_digest(pieces: list) -> str:
    def line(piece) -> str:
        values = (
            piece.kind, piece.cell_x, piece.cell_y,
            piece.tile_index, piece.tile_uuid or "",
            piece.rotation, piece.x, piece.y, piece.z,
            piece.width, piece.depth, piece.height,
        )
        return "|".join(
            format(value, ".15g") if isinstance(value, float) else str(value)
            for value in values
        )

    return hashlib.sha256(
        "\n".join(sorted(map(line, pieces))).encode()
    ).hexdigest()


def _python_report(save_path: Path) -> dict:
    db = SaveDatabase(save_path)
    worlds = discover_worlds(db)
    with db.connect() as connection:
        portals = connection.execute(
            "SELECT worldIdA, worldIdB FROM Portal"
        ).fetchall()
    underground = []
    for world in worlds:
        if world.kind != "underground":
            continue
        try:
            row_id, value = _load_terrain_table(
                db, world_id=world.world_id
            )
        except ValueError:
            underground.append({
                "worldId": world.world_id, "rowId": None,
                "status": "unavailable", "tunnels": 0,
                "caveCells": 0, "pocketCells": 0, "caveGroups": 0,
                "caveGroupsSourceAware": 0, "caveGroupsSourceComplete": 0,
                "caveGroupsSourceOverlap": 0,
                "pocketGroups": 0, "pocketGroupsComplete": 0, "pocketGroupsSplit": 0,
                "points": 0,
                "tunnelDigest": _tunnel_digest([]),
                "placementDigest": _placement_digest([]),
            })
            continue
        tunnels = _extract_tunnels(value)
        caves = extract_caves(value)
        pockets = extract_pockets(value)
        cave_groups = reconstruct_logical_structures(caves)
        logical_pockets = reconstruct_logical_pockets(pockets, _dimensions_from_name)
        underground.append({
            "worldId": world.world_id, "rowId": row_id,
            "status": (
                "tunnels" if tunnels else
                "placements" if caves or pockets else "no-layout"
            ),
            "tunnels": len(tunnels), "caveCells": len(caves),
            "pocketCells": len(pockets),
            "caveGroups": len(cave_groups),
            "caveGroupsSourceAware": sum(g.source_aware for g in cave_groups),
            "caveGroupsSourceComplete": sum(
                g.source_complete is True for g in cave_groups
            ),
            "caveGroupsSourceOverlap": sum(
                g.source_overlap_cells or 0 for g in cave_groups
            ),
            "pocketGroups": len(logical_pockets),
            "pocketGroupsComplete": sum(p.complete for p in logical_pockets),
            "pocketGroupsSplit": sum(
                len(p.fragments) > 1 for p in logical_pockets
            ),
            "points": sum(len(tunnel["points"]) for tunnel in tunnels),
            "tunnelDigest": _tunnel_digest(tunnels),
            "placementDigest": _placement_digest(caves + pockets),
        })
    return {
        "worlds": [
            {
                "id": w.world_id, "kind": w.kind,
                "depth": w.depth, "label": w.label,
            }
            for w in sorted(worlds, key=lambda w: w.world_id)
        ],
        "portals": {
            "count": len(portals),
            "resolved": sum(
                row["worldIdA"] != 65535 and row["worldIdB"] != 65535
                for row in portals
            ),
        },
        "underground": underground,
    }


def compare_reports(expected: dict, actual: dict) -> list[str]:
    """Return readable mismatches without printing any raw save data."""
    failures = []
    if expected.get("worlds") != actual.get("worlds"):
        failures.append("World identity, depth or label mismatch")
    if expected.get("portals") != actual.get("portals"):
        failures.append("Portal totals or resolution mismatch")
    python_worlds = {
        item["worldId"]: item for item in expected.get("underground", [])
    }
    browser_worlds = {
        item["worldId"]: item for item in actual.get("underground", [])
    }
    if python_worlds.keys() != browser_worlds.keys():
        failures.append("Underground world ID set mismatch")
    for world_id in sorted(python_worlds.keys() & browser_worlds.keys()):
        python_info, browser_info = python_worlds[world_id], browser_worlds[world_id]
        for key in (
            "rowId", "status", "tunnels", "caveCells", "pocketCells",
            "caveGroups", "caveGroupsSourceAware",
            "caveGroupsSourceComplete", "caveGroupsSourceOverlap",
            "pocketGroups", "pocketGroupsComplete",
            "pocketGroupsSplit", "points", "tunnelDigest", "placementDigest",
        ):
            if python_info.get(key) != browser_info.get(key):
                failures.append(
                    f"Underground world {world_id}: {key} mismatch"
                )
    return failures


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/verify_browser_parity.py /path/to/save.db",
              file=sys.stderr)
        return 2
    save_path = Path(sys.argv[1]).expanduser().resolve()
    db = SaveDatabase(save_path)
    db.validate()
    reference = _python_report(save_path)
    command = ["node", str(ROOT / "web" / "verify-save.mjs"), str(save_path)]
    try:
        browser = subprocess.run(
            command, check=True, capture_output=True, text=True,
            cwd=ROOT, timeout=180,
        )
        result = json.loads(browser.stdout)
    except (OSError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print("Browser parity probe failed; install web dependencies with npm ci.",
              file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 2
    mismatches = compare_reports(reference, result)
    if mismatches:
        print("FAIL: Python and browser decoders disagree:")
        for item in mismatches:
            print(" - " + item)
        return 1
    print("PASS: Python and browser decoders agree on "
          + str(len(reference["worlds"])) + " worlds, "
          + str(reference["portals"]["count"]) + " portals, and "
          + str(len(reference["underground"])) + " underground worlds.")
    print("Checked saved records, world labels, geometry counts, "
          "and SHA-256 digests of tunnel coordinates and placement data.")
    print("The save was opened locally and read-only; no report was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
