"""Run the BUILT SM Atlas UI against a private real or synthetic Survival save.

Development-only; never uploads, copies or commits save data. The browser is
network-isolated to localhost and screenshots are deliberately disabled.

Examples:
    python scripts/browser_acceptance.py --save "/path/to/save.db"
    python scripts/browser_acceptance.py --synthetic

Prerequisites: pip install -e . && pip install playwright && playwright install
chromium; cd web && npm ci && npm run build
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sqlite3
import tempfile
from threading import Thread

from playwright.sync_api import sync_playwright

from sm_atlas.database import SaveDatabase
from sm_atlas.underground_features import extract_caves, extract_pockets
from sm_atlas.underground_tunnels import _extract_tunnels, _load_terrain_table
from sm_atlas.worlds import discover_worlds

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web" / "dist"
MISSING_WORLD = 65535


def expected_from_python(path: Path) -> dict:
    """Independently derive aggregate expectations; never expose raw save bytes."""
    database = SaveDatabase(path)
    database.validate()
    worlds = discover_worlds(database)
    with database.connect() as connection:
        portals = [
            tuple(row) for row in connection.execute(
                "SELECT id, worldIdA, xA, yA, worldIdB, xB, yB FROM Portal"
            )
        ]
    underground = []
    for world in worlds:
        if world.kind != "underground":
            continue
        # Distinct grid cells, not raw endpoints (several portals can share XY).
        portal_cells: set[tuple[int, int]] = set()
        for record_id, a, xa, ya, b, xb, yb in portals:
            if a == world.world_id and a != MISSING_WORLD:
                portal_cells.add((xa, ya))
            if b == world.world_id and b != MISSING_WORLD:
                portal_cells.add((xb, yb))
        try:
            _, terrain = _load_terrain_table(database, world_id=world.world_id)
            tunnels = _extract_tunnels(terrain)
            caves = extract_caves(terrain)
            pockets = extract_pockets(terrain)
        except ValueError:
            tunnels, caves, pockets = [], [], []
        underground.append({
            "id": world.world_id,
            "label": world.label,
            "tunnels": len(tunnels),
            "caves": len(caves),
            "pockets": len(pockets),
            "portals": len(portal_cells),
        })
    return {
        "worlds": len(worlds),
        "portals": len(portals),
        "underground": underground,
    }


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format, *_args):
        # Do not leak a path or filename into CI logs.
        pass


@contextmanager
def local_static_server():
    handler = partial(QuietHandler, directory=str(DIST))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def verify_browser(path: Path, expected: dict, *, timeout_ms: int = 240_000) -> None:
    if not (DIST / "vendor" / "sql-wasm.wasm").is_file():
        raise FileNotFoundError(
            "Static preview is missing. Run: cd web && npm ci && npm run build"
        )
    with local_static_server() as origin, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                service_workers="block", viewport={"width": 1440, "height": 900}
            )
            blocked_urls = []
            script_errors = []

            def enforce_local_only(route):
                url = route.request.url
                if url == origin or url.startswith(origin + "/"):
                    route.continue_()
                else:
                    # Block accidental third-party network access before it happens.
                    blocked_urls.append(url)
                    route.abort()

            context.route("**/*", enforce_local_only)
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            page.on("pageerror", lambda error: script_errors.append(str(error)))
            page.goto(origin + "/", wait_until="load")
            page.locator("#save-input").set_input_files(str(path))
            page.locator("#stat-worlds").get_by_text(
                str(expected["worlds"]), exact=True
            ).wait_for()
            page.locator("#stat-portals").get_by_text(
                str(expected["portals"]), exact=True
            ).wait_for()

            total = len(expected["underground"])
            page.locator("#stat-underground").get_by_text(
                str(total), exact=True
            ).wait_for()

            if total:
                # Wait until worker scanning and initial automatic selection are done.
                # Normal saves contain fewer than the 32-world display scan cap.
                checked = min(total, 32)
                page.locator("#world-coverage-summary").get_by_text(
                    f"of {checked} checked underground worlds", exact=False
                ).wait_for()

            for info in expected["underground"]:
                world_id = info["id"]
                entry = page.locator(
                    f'#world-list .world-entry[data-world-id="{world_id}"]'
                )
                entry.click()
                page.wait_for_function(
                    """() => {
                      const s = document.querySelector('#tunnel-status')?.textContent || '';
                      return s.length > 0 && !s.startsWith('Reading saved');
                    }""",
                    timeout=timeout_ms,
                )
                for css, key in (
                    ("#tunnel-map .tunnel-line", "tunnels"),
                    ("#tunnel-map .saved-footprint.cave", "caves"),
                    ("#tunnel-map .saved-footprint.pocket", "pockets"),
                    ("#tunnel-map .portal-cell", "portals"),
                ):
                    count = page.locator(css).count()
                    if count != info[key]:
                        raise AssertionError(
                            f"World #{world_id}: {key} mismatch "
                            f"(Python {info[key]}, browser {count})"
                        )
                message = page.locator("#tunnel-status").inner_text()
                if "Cannot inspect this world:" in message:
                    raise AssertionError(f"World #{world_id}: browser decoder failed")
            if blocked_urls:
                raise AssertionError(
                    "Browser attempted a third-party request; it was blocked"
                )
            if script_errors:
                raise AssertionError(
                    "Chromium reported JavaScript errors while parsing save"
                )
            print(
                "PASS: Chromium and independent Python agree on "
                f"{expected['worlds']} worlds, {expected['portals']} portals, "
                f"and rendered underground data in {total} worlds."
            )
            print(
                "No save was uploaded, copied or logged. "
                "This checks rendered geometry counts, not voxel walkability."
            )
        finally:
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--save", type=Path, help="Private local save.db path")
    source.add_argument("--synthetic", action="store_true",
                        help="Run on a temporary generated SQLite test save")
    parser.add_argument("--timeout", type=int, default=240,
                        help="Timeout per browser step in seconds (default: 240)")
    args = parser.parse_args()
    if args.timeout < 5 or args.timeout > 900:
        parser.error("--timeout must be between 5 and 900 seconds")

    if args.synthetic:
        from browser_smoke import make_synthetic_save

        with tempfile.TemporaryDirectory(prefix="sm-atlas-acceptance-") as folder:
            path = Path(folder) / "generated.db"
            make_synthetic_save(path)
            verify_browser(path, expected_from_python(path),
                           timeout_ms=args.timeout * 1000)
    else:
        path = args.save.expanduser().resolve(strict=True)
        if not path.is_file():
            parser.error("--save must be a readable file")
        verify_browser(path, expected_from_python(path),
                       timeout_ms=args.timeout * 1000)


if __name__ == "__main__":
    main()
