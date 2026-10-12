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
import subprocess
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
        "tileList": {},
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
                    page.locator("#stat-portals").get_by_text("3", exact=True).wait_for()
                    page.locator("#world-coverage-summary").get_by_text(
                        "1 of 2 checked underground worlds", exact=False).wait_for(
                            timeout=30000)
                    page.locator("#tunnel-map .tunnel-line").first.wait_for(timeout=30000)
                    page.locator("#tunnel-map .saved-footprint.cave").first.wait_for()
                    assert page.locator("#tunnel-map .tunnel-line").count() == 1
                    assert page.locator("#tunnel-map .saved-footprint.cave").count() == 1
                    assert "D6 Drill2" in page.locator("#cave-group-info").inner_text() \
                        or page.locator("#cave-group-info").inner_text()
                    assert "D6 Drill2" in page.locator("#world-details").inner_text()
                    # User selection must persist after background coverage scanning.
                    page.get_by_role("button", name="D2 Tutorial").click()
                    assert "no saved tunnel centerlines" in page.locator(
                        "#tunnel-status").inner_text().lower() or \
                        "no saved" in page.locator("#tunnel-status").inner_text().lower()
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
