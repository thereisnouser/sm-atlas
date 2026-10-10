/**
 * Build a self-contained static browser distribution without a backend.
 * The exact sql.js version is pinned; no third-party runtime requests remain.
 */
import { copyFile, mkdir, readFile, rm, stat } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const dist = join(root, "dist");
const vendor = join(root, "node_modules", "sql.js");
const browserFiles = ["index.html", "styles.css", "app.mjs",
  "save-reader.mjs", "tunnel-reader.mjs", "tile-catalog.mjs", "save-worker.js"];
const vendorFiles = ["sql-wasm.js", "sql-wasm.wasm"];

const pkg = JSON.parse(await readFile(join(vendor, "package.json"), "utf8"));
const declared = JSON.parse(await readFile(join(root, "package.json"), "utf8"));
if (pkg.version !== declared.dependencies["sql.js"]) {
  throw new Error("The installed SQLite runtime does not match the pinned version");
}
for (const filename of vendorFiles) {
  const file = join(vendor, "dist", filename);
  const stats = await stat(file);
  if (!stats.isFile() || stats.size < 1024) {
    throw new Error("SQLite WASM build asset is missing or invalid: " + filename);
  }
}
await rm(dist, { recursive: true, force: true });
await mkdir(join(dist, "vendor"), { recursive: true });
for (const filename of browserFiles) {
  await copyFile(join(root, filename), join(dist, filename));
}
for (const filename of vendorFiles) {
  await copyFile(join(vendor, "dist", filename), join(dist, "vendor", filename));
}
await copyFile(join(root, "..", "THIRD_PARTY_NOTICES.md"),
  join(dist, "THIRD_PARTY_NOTICES.md"));
for (const name of ["LICENSE", "LICENSE.md", "LICENSE.txt"]) {
  try {
    await copyFile(join(vendor, name), join(dist, "vendor", "LICENSE.sql.js.txt"));
    break;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
}
console.log("Built self-hosted SM Atlas browser preview in web/dist/");
