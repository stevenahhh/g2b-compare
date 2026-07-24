import { build } from "esbuild";
import { rm } from "node:fs/promises";

await rm("dist", { force: true, recursive: true });

const shared = {
  bundle: true,
  external: ["electron", "exceljs"],
  format: "esm",
  platform: "node",
  sourcemap: false,
  target: "node24"
};

await Promise.all([
  build({ ...shared, entryPoints: ["src/main/index.ts"], outdir: "dist/main" }),
  build({ ...shared, entryPoints: ["src/preload/index.ts"], outdir: "dist/preload" })
]);
