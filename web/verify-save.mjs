/**
 * Developer-only parity probe for a private local save.db.
 * Uses the browser's actual decoding modules with sql.js; no uploads.
 * Called by scripts/verify_browser_parity.py (JSON stdout is local only).
 */
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import initSqlJs from "sql.js";
import { assertSqliteHeader, extractSaveData } from "./save-reader.mjs";
import { extractTerrainTunnels, summarizeSavedLayout } from "./tunnel-reader.mjs";

function tunnelDigest(tunnels) {
  const hash = createHash("sha256");
  const buffer = Buffer.alloc(12);
  const view = new DataView(buffer.buffer, buffer.byteOffset, 12);
  for (const tunnel of [...tunnels].sort((a, b) => a.id - b.id)) {
    hash.update(tunnel.id + ":" + tunnel.type + ":" + tunnel.points.length + "\n");
    for (const point of tunnel.points) {
      for (let axis = 0; axis < 3; axis++) {
        view.setFloat32(axis * 4, point[axis], false);
      }
      hash.update(buffer);
    }
  }
  return hash.digest("hex");
}

function placementDigest(footprints) {
  const lines = footprints.map((p) => [
    p.kind, p.cellX, p.cellY, p.tileIndex, p.tileUuid || "",
    p.rotation, p.x, p.y, p.z, p.width, p.depth, p.height,
  ].join("|"));
  lines.sort();
  return createHash("sha256").update(lines.join("\n")).digest("hex");
}

async function main() {
  if (process.argv.length !== 3) {
    throw new Error("Usage: node web/verify-save.mjs /local/path/to/save.db");
  }
  const bytes = new Uint8Array(await readFile(process.argv[2]));
  assertSqliteHeader(bytes);
  const SQL = await initSqlJs();
  const db = new SQL.Database(bytes);
  try {
    const saved = extractSaveData(db);
    const worlds = saved.worlds
      .map((w) => ({ id: w.id, kind: w.kind, depth: w.depth, label: w.label }))
      .sort((a, b) => a.id - b.id);
    const underground = [];
    for (const world of worlds.filter((w) => w.kind === "underground")) {
      const result = extractTerrainTunnels(db, world.id);
      const coverage = summarizeSavedLayout(result);
      const tunnels = result.tunnels || [];
      const footprints = result.footprints || [];
      underground.push({
        worldId: world.id, rowId: result.rowId ?? null,
        status: coverage.status, tunnels: coverage.tunnels,
        caveCells: coverage.caveCells, pocketCells: coverage.pocketCells,
        caveGroups: coverage.caveGroups,
        caveGroupsSourceAware: result.caveGroups?.filter((g) => g.sourceAware).length ?? 0,
        caveGroupsSourceComplete: result.caveGroups?.filter((g) =>
          g.sourceComplete === true).length ?? 0,
        caveGroupsSourceOverlap: result.caveGroups?.reduce((sum,g) =>
          sum + (g.sourceOverlapCells || 0),0) ?? 0,
        pocketGroups: result.pocketGroups?.length ?? 0,
        pocketGroupsComplete: result.pocketGroups?.filter((g) => g.complete).length ?? 0,
        pocketGroupsSplit: result.pocketGroups?.filter((g) =>
          g.fragmentCount > 1).length ?? 0,
        points: tunnels.reduce((n, t) => n + t.points.length, 0),
        tunnelDigest: tunnelDigest(tunnels),
        placementDigest: placementDigest(footprints),
      });
    }
    const resolved = saved.portals.filter((p) => p.resolved).length;
    process.stdout.write(JSON.stringify({
      worlds, portals: { count: saved.portals.length, resolved }, underground,
    }) + "\n");
  } finally {
    db.close();
  }
}

main().catch((error) => {
  process.stderr.write("Browser save decoding failed: "
    + (error instanceof Error ? error.message : String(error)) + "\n");
  process.exitCode = 1;
});
