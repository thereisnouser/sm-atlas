"""Open the actual static SM Atlas build in Chromium with a synthetic save.

This tests the complete file picker -> Web Worker -> local SQLite WASM ->
world coverage -> cave map path. It deliberately does not use or upload any
private test save. Install Python Playwright + its Chromium browser to run.
"""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sqlite3
import struct
import tempfile
from threading import Thread

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
MARKER = bytes.fromhex("5297769df4514e5e9a388b0f95e2edad")


def be_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack(">H", len(encoded)) + encoded


def lz4_literals(raw: bytes) -> bytes:
    # A valid standard raw LZ4 block without backward matches.
    token = min(len(raw), 15) << 4
    result = bytearray([token])
    if len(raw) >= 15:
        additional = len(raw) - 15
        while additional >= 255:
            result.append(255)
            additional -= 255
        result.append(additional)
    result.extend(raw)
    return bytes(result)


def world_blob(world_id: int, classname: str, path: str, depth: int | None) -> bytes:
    import json

    terrain = {"path": path}
    if depth is not None:
        terrain["depth"] = depth
    payload = (struct.pack(">I", 551234)
               + be_string("world.lua")
               + be_string(classname)
               + be_string(json.dumps(terrain, separators=(",", ":"))))
    compressed = lz4_literals(payload)
    return (MARKER + struct.pack(">H", 0) + struct.pack("<I", 0)
            + struct.pack(">H", world_id) + struct.pack("<I", 3)
            + bytes([len(compressed) if len(compressed) <= 255 else 0])
            + compressed)


class LuaBits:
    def __init__(self) -> None:
        self.bits: list[int] = []

    def add(self, value: int, count: int) -> None:
        for bit in range(count - 1, -1, -1):
            self.bits.append((value >> bit) & 1)

    def align(self) -> None:
        while len(self.bits) % 8:
            self.bits.append(0)

    def write(self, value) -> None:
        if isinstance(value, str):
            raw = value.encode("utf-8")
            self.add(4, 8)
            self.add(len(raw), 32)
            self.align()
            for byte in raw:
                self.add(byte, 8)
        elif isinstance(value, int):
            self.add(6, 8)
            self.add(value & 0xFFFFFFFF, 32)
        elif isinstance(value, dict):
            self.add(5, 8)
            self.add(len(value), 32)
            self.add(0, 1)  # associative LUA table, not a packed array
            for key, entry in value.items():
                self.write(key)
                self.write(entry)
        elif isinstance(value, tuple) and len(value) == 4 and value[0] == "vec3":
            self.add(0x64, 8)
            self.add(10003, 32)
            for coordinate in value[1:]:
                self.add(struct.unpack(">I", struct.pack(">f", coordinate))[0], 32)
        elif isinstance(value, tuple) and len(value) == 2 and value[0] == "uuid":
            self.add(0x64, 8)
            self.add(10001, 32)
            for byte in value[1]:
                self.add(byte, 8)
        else:
            raise TypeError(f"Unsupported synthetic LUA type: {type(value)}")

    def finish(self) -> bytes:
        self.align()
        result = bytearray()
        for start in range(0, len(self.bits), 8):
            byte = 0
            for bit in self.bits[start:start + 8]:
                byte = (byte << 1) | bit
            result.append(byte)
        return bytes(result)


def terrain_blob(world_id: int) -> bytes:
    # Two-point saved line, one cave placement, and no assumed walkable floors.
    # Exact catalog UUID of the 2x2x2 known passage pocket (disk bytes reversed).
    pocket_uuid = bytes.fromhex(
        "034b98c5c3ce4fbcb055cd052d9864ca"
    )[::-1]
    # Two 1x2 fragments forming one 2x2 known pocket.
    pocket_left = 12 | (0x14 << 16)
    pocket_right = 12 | (1 << 8) | (0x14 << 16) | (1 << 24)
    terrain = {
        "tunnels": {
            17: {
                "tunnelType": "TtVeinT4",
                "positions": {
                    1: ("vec3", 0.0, 0.0, 0.0),
                    2: ("vec3", 64.0, 32.0, 0.0),
                },
            }
        },
        "caves": {0: {0: {1: 7}}},  # index 7, a 64x64 cell at z=0
        "pockets": {0: {0: {1: pocket_left, 2: pocket_right}}},
        "tileList": {12: ("uuid", pocket_uuid)},
    }
    bits = LuaBits()
    for b in b"LUA":
        bits.add(b, 8)
    bits.add(1, 32)
    bits.write(terrain)
    payload = lz4_literals(bits.finish())
    key = bytes([1, 2, 3])
    return (bytes(16) + struct.pack(">H", len(key)) + key
            + struct.pack(">H", world_id) + bytes([7])
            + struct.pack(">I", len(payload)) + payload)


def make_synthetic_save(target: Path) -> None:
    db = sqlite3.connect(target)
    try:
        db.executescript("""
            CREATE TABLE GenericData (
                uid BLOB, key BLOB, worldId INTEGER, flags INTEGER, data BLOB
            );
            CREATE TABLE ScriptData (
                uid BLOB, key BLOB, worldId INTEGER, flags INTEGER, data BLOB
            );
            CREATE TABLE Portal (
                id INTEGER, worldIdA INTEGER, xA INTEGER, yA INTEGER,
                worldIdB INTEGER, xB INTEGER, yB INTEGER, data BLOB
            );
        """)
        worlds = [
            (1, "Overworld", "Overworld.lua", None),
            (13, "UndergroundWorldTutorial", "Tutorial.lua", 2),
            (23, "UndergroundWorldDrill2", "Drill2.lua", 6),
        ]
        for world_id, cls, path, depth in worlds:
            db.execute("INSERT INTO GenericData VALUES (?, ?, ?, 3, ?)", (
                MARKER, bytes(4), world_id, world_blob(world_id, cls, path, depth),
            ))
        db.execute("INSERT INTO ScriptData VALUES (?, ?, ?, 7, ?)",
                   (bytes(16), bytes([1, 2, 3]), 23, terrain_blob(23)))
        portals = [
            (1, 1, 0, 0, 13, 0, 0, None),
            (2, 1, 5, 7, 23, 0, 0, None),
            (3, 23, 1, 0, 65535, 0, 0, None),
            # Same cell as #2 in Drill2 and #1 in Tutorial.
            (4, 23, 0, 0, 13, 0, 0, None),
        ]
        db.executemany("INSERT INTO Portal VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       portals)
        db.commit()
    finally:
        db.close()


def main() -> None:
    # CI runs npm ci and build first; local runs can do the same manually.
    if not (WEB / "dist" / "vendor" / "sql-wasm.wasm").is_file():
        raise RuntimeError("Build browser first: cd web && npm ci && npm run build")
    with tempfile.TemporaryDirectory(prefix="sm-atlas-browser-smoke-") as directory:
        save = Path(directory) / "synthetic_test.db"
        make_synthetic_save(save)
        handler = partial(SimpleHTTPRequestHandler, directory=str(WEB / "dist"))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = "http://127.0.0.1:" + str(server.server_port)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 900})
                    errors = []
                    offsite = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on("request", lambda request: offsite.append(request.url)
                            if not request.url.startswith(url + "/") else None)
                    page.goto(url, wait_until="load")
                    page.locator("#save-input").set_input_files(str(save))
                    page.locator("#stat-worlds").get_by_text("3", exact=True).wait_for()
                    page.locator("#stat-underground").get_by_text("2", exact=True).wait_for()
                    page.locator("#stat-portals").get_by_text("4", exact=True).wait_for()
                    page.locator("#world-coverage-summary").get_by_text(
                        "1 of 2 checked underground worlds", exact=False).wait_for(
                            timeout=30000)
                    page.locator("#tunnel-map .tunnel-line").first.wait_for(timeout=30000)
                    page.locator("#tunnel-map .saved-footprint.cave").first.wait_for()
                    page.locator("#tunnel-map .pocket-group").first.wait_for()
                    assert page.locator("#tunnel-map .pocket-group").count() == 1
                    assert page.locator("#tunnel-map .saved-footprint.pocket").count() == 2
                    # The stacked pocket reaches Z 16–32, but the cave and
                    # horizontal tunnel line only occupy Z 0–16.
                    page.locator("#height-mode").select_option("band")
                    assert "Saved Z 0 to 16" in page.locator("#height-band-label").inner_text()
                    page.locator("#height-band").focus()
                    page.locator("#height-band").press("ArrowRight")
                    assert "Saved Z 16 to 32" in page.locator("#height-band-label").inner_text()
                    assert page.locator("#tunnel-map .saved-footprint.cave").count() == 0
                    assert page.locator("#tunnel-map .saved-footprint.pocket").count() == 2
                    assert page.locator("#tunnel-map .tunnel-line").count() == 0
                    assert page.locator("#tunnel-map .portal-cell").count() == 2
                    page.locator("#height-mode").select_option("all")
                    assert page.locator("#tunnel-map .saved-footprint.cave").count() == 1
                    assert page.locator("#tunnel-map .tunnel-line").count() == 1
                    # A recorded tunnel line is selectable, even without a tile catalog UUID.
                    page.locator("#tunnel-map .tunnel-line").first.click(force=True)
                    assert "Saved tunnel #17" in page.locator("#cave-group-info").inner_text()
                    assert "TtVeinT4" in page.locator("#cave-group-info").inner_text()
                    assert "NOT a verified" in page.locator("#cave-group-info").inner_text()
                    assert page.locator("#tunnel-map .tunnel-line.active").count() == 1
                    page.locator("#map-search-category").select_option("tunnel")
                    page.locator("#map-search-status").get_by_text(
                        "1 matching saved object", exact=False).wait_for()
                    page.locator("#map-search-results .map-search-result").click()
                    assert page.locator("#map-zoom-level").inner_text() == "400%"
                    assert "Saved tunnel #17" in page.locator("#cave-group-info").inner_text()
                    page.locator("#map-zoom-reset").click()
                    page.locator("#map-search-category").select_option("all")
                    # A source-backed category can be browsed without typing.
                    page.locator("#map-search-category").select_option("passage")
                    page.locator("#map-search-status").get_by_text(
                        "1 matching saved object", exact=False).wait_for()
                    page.locator("#map-search-category").select_option("all")
                    page.locator("#map-search-input").fill("passage")
                    page.locator("#map-search-status").get_by_text(
                        "1 matching saved object", exact=False).wait_for()
                    page.locator("#map-search-results .map-search-result").click()
                    assert "Logical pocket placement #1" in page.locator(
                        "#cave-group-info").inner_text()
                    assert "source coverage complete" in page.locator(
                        "#cave-group-info").inner_text()
                    page.locator("#map-zoom-reset").click()
                    page.locator("#map-search-input").fill("")
                    # Search returns only saved objects, then focuses their actual XY.
                    page.locator("#map-search-input").fill("cave")
                    page.locator("#map-search-status").get_by_text(
                        "1 matching saved object", exact=False).wait_for()
                    page.locator("#height-mode").select_option("band")
                    page.locator("#height-band").focus()
                    page.locator("#height-band").press("ArrowRight")
                    assert page.locator("#tunnel-map .saved-footprint.cave").count() == 0
                    page.locator("#map-search-results .map-search-result").click()
                    assert page.locator("#height-mode").input_value() == "all"
                    assert "Placement group #1" in page.locator("#cave-group-info").inner_text()
                    assert page.locator("#map-zoom-level").inner_text() == "400%"
                    page.locator("#map-zoom-reset").click()
                    page.locator("#map-search-input").fill("unknown-mineral")
                    page.locator("#map-search-status").get_by_text(
                        "0 matching saved objects", exact=False).wait_for()
                    page.locator("#map-search-input").fill("")
                    # From an empty underground world, search another world's assets.
                    page.locator("#map-search-scope").select_option("all")
                    page.locator("#map-search-category").select_option("tunnel")
                    page.locator("#world-list .world-entry").filter(
                        has_text="D2 Tutorial").click()
                    page.locator("#map-search-results .map-search-result").get_by_text(
                        "TtVeinT4", exact=False).wait_for(timeout=30000)
                    page.locator("#map-search-results .map-search-result").click()
                    page.locator("#world-details").get_by_text(
                        "D6 Drill2", exact=False).first.wait_for(timeout=30000)
                    assert "Saved tunnel #17" in page.locator("#cave-group-info").inner_text()
                    assert page.locator("#tunnel-map .tunnel-line.active").count() == 1
                    page.locator("#map-zoom-reset").click()
                    page.locator("#map-search-category").select_option("passage")
                    page.locator("#map-search-results .map-search-result").get_by_text(
                        "D6 Drill2", exact=False).wait_for(timeout=30000)
                    page.locator("#map-search-category").select_option("all")
                    page.locator("#map-search-input").fill("cave")
                    page.locator("#map-search-status").get_by_text(
                        "1 matching saved object", exact=False).wait_for(timeout=30000)
                    page.locator("#world-list .world-entry").filter(
                        has_text="D2 Tutorial").click()
                    page.locator("#map-search-results .map-search-result").get_by_text(
                        "D6 Drill2", exact=False).wait_for()
                    page.locator("#map-search-results .map-search-result").click()
                    page.locator("#world-details").get_by_text(
                        "D6 Drill2", exact=False).first.wait_for(timeout=30000)
                    page.locator("#map-zoom-level").get_by_text("400%", exact=True).wait_for()
                    assert "Placement group #1" in page.locator(
                        "#cave-group-info").inner_text()
                    page.locator("#map-search-scope").select_option("current")
                    page.locator("#map-search-input").fill("")
                    page.locator("#map-zoom-reset").click()
                    # The map camera is independent of geometry and UI selection.
                    assert page.locator("#map-zoom-level").inner_text() == "100%"
                    page.locator("#map-zoom-in").click()
                    assert page.locator("#map-zoom-level").inner_text() == "150%"
                    assert page.locator("#tunnel-map").get_attribute("viewBox") != "0 0 1000 620"
                    page.locator("#show-tunnels").uncheck()
                    assert page.locator("#map-zoom-level").inner_text() == "150%"
                    page.locator("#show-tunnels").check()
                    page.locator("#map-zoom-reset").click()
                    assert page.locator("#tunnel-map").get_attribute("viewBox") == "0 0 1000 620"
                    page.locator("#map-zoom-in").click()
                    assert page.locator("#map-zoom-level").inner_text() == "150%"
                    page.locator("#world-list .world-entry").filter(
                        has_text="D2 Tutorial").click()
                    assert page.locator("#map-zoom-level").inner_text() == "100%"
                    page.locator("#world-list .world-entry").filter(
                        has_text="D6 Drill2").click()
                    page.locator("#tunnel-map .tunnel-line").first.wait_for()
                    assert page.locator("#map-zoom-level").inner_text() == "100%"
                    page.locator("#tunnel-map .portal-cell").first.wait_for()
                    assert page.locator("#tunnel-map .portal-cell").count() == 2
                    page.locator("#tunnel-map .portal-cell").first.click()
                    assert "2 saved portal endpoints" in page.locator(
                        "#cave-group-info").inner_text()
                    assert "Portal #2" in page.locator("#cave-group-info").inner_text()
                    assert "Portal #4" in page.locator("#cave-group-info").inner_text()
                    page.locator("#cave-group-info .portal-go").filter(
                        has_text="D2 Tutorial").click()
                    assert "D2 Tutorial" in page.locator("#world-details").inner_text()
                    page.locator("#world-list .world-entry").filter(
                        has_text="D6 Drill2").click()
                    page.locator("#tunnel-map .portal-cell").first.wait_for()
                    page.locator("#tunnel-map .portal-cell").first.click()
                    page.locator("#show-portals").uncheck()
                    assert page.locator("#tunnel-map .portal-cell").count() == 0
                    page.locator("#show-portals").check()
                    assert page.locator("#tunnel-map .portal-cell").count() == 2
                    assert page.locator("#tunnel-map .tunnel-line").count() == 1
                    assert page.locator("#tunnel-map .saved-footprint.cave").count() == 1
                    assert "Portal #2" in page.locator(
                        "#cave-group-info").inner_text()
                    assert "D6 Drill2" in page.locator("#world-details").inner_text()
                    # User selection must persist after background coverage scanning.
                    page.locator("#world-list .world-entry").filter(
                        has_text="D2 Tutorial").click()
                    page.locator("#tunnel-status").get_by_text(
                        "No compatible terrain record", exact=False).wait_for(
                            timeout=30000)
                    page.locator("#tunnel-map .portal-cell").first.wait_for(
                        timeout=30000)
                    assert page.locator("#tunnel-map .tunnel-line").count() == 0
                    assert page.locator("#tunnel-map .portal-cell").count() == 1
                    page.locator("#world-list .world-entry").filter(
                        has_text="D6 Drill2").click()
                    page.locator("#tunnel-map .tunnel-line").first.wait_for(
                        timeout=30000)
                    assert not errors, "Browser JavaScript errors: " + repr(errors)
                    assert not offsite, "Unexpected remote requests: " + repr(offsite)
                    page.screenshot(path=str(WEB / "smoke-result.png"), full_page=True)
                    print("PASS: Chromium loaded local SQLite WASM, parsed the "
                          "synthetic save in a Worker, found saved cave lines, "
                          "selected the mapped underground level and made "
                          "no third-party requests.")
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
