import { readFile } from "node:fs/promises";

const expected = {
  electron: "43.2.0",
  vite: "8.1.5",
  typescript: "7.0.2",
  vitest: "4.1.10",
  "@playwright/test": "1.61.1",
  "electron-builder": "26.15.3",
  esbuild: "0.28.1",
  jszip: "3.10.1",
  "decimal.js": "10.6.0",
  zod: "4.4.3",
  exceljs: "4.4.0"
};
const argv = process.argv.slice(2);
const electronIndex = argv.indexOf("--expect-electron");
if (electronIndex !== -1) {
  expected.electron = argv[electronIndex + 1] ?? "";
}
const packageJson = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
for (const [name, version] of Object.entries(expected)) {
  const actual = packageJson.dependencies?.[name] ?? packageJson.devDependencies?.[name];
  if (actual !== version) {
    console.error(`TOOLCHAIN_VERSION_MISMATCH ${name}: expected ${version}, received ${actual ?? "missing"}`);
    process.exitCode = 1;
  }
}
if (process.exitCode !== 1) {
  console.log("TOOLCHAIN_VERSION_ASSERTION_PASS");
}
