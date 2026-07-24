import { readdir } from "node:fs/promises";
import { join } from "node:path";

const allowedFiles = [
  "dist/main/index.js",
  "dist/preload/index.js",
  "dist/renderer/index.html",
  "dist/renderer/assets/index.js"
];

const listFiles = async (directory) => {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? listFiles(path) : [path.replaceAll("\\", "/")];
  }));
  return nested.flat();
};

let actualFiles;
try {
  actualFiles = await listFiles("dist");
} catch {
  console.error("BUILD_INVENTORY_MISSING_DIST");
  process.exitCode = 1;
  actualFiles = [];
}
const unexpected = actualFiles.filter((file) => !allowedFiles.includes(file));
const missing = allowedFiles.filter((file) => !actualFiles.includes(file));
if (unexpected.length > 0 || missing.length > 0) {
  console.error(JSON.stringify({ status: "BUILD_INVENTORY_MISMATCH", missing, unexpected }, null, 2));
  process.exitCode = 1;
} else {
  console.log(JSON.stringify({ status: "BUILD_INVENTORY_PASS", files: actualFiles }, null, 2));
}
