import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";
import { importLegacyWorkbook } from "../../src/legacy/import.js";

const dataset = resolve(import.meta.dirname, "..", "..", "..", "dataset");
const sources: { readonly sha256: string; readonly path: string }[] = [];
for (const filename of await readdir(dataset)) {
  if (filename.toLowerCase().endsWith(".xlsx") && !filename.startsWith("~$")) {
    const path = resolve(dataset, filename);
    sources.push({
      sha256: createHash("sha256").update(await readFile(path)).digest("hex"),
      path
    });
  }
}

const summaries = [];
for (const source of sources.toSorted((left, right) =>
  left.sha256.localeCompare(right.sha256)
)) {
  const imported = await importLegacyWorkbook(source.path);
  summaries.push({
    profileId: imported.profileId,
    capacity: imported.capacity,
    items: imported.items.length,
    externalLinks: imported.baselineInventory.externalLinks.count,
    inheritedFormulaWarnings:
      imported.inheritedWarnings.originalFormulaCells.length,
    sourceSha256: imported.sourceSha256
  });
}
process.stdout.write(`${JSON.stringify(summaries)}\n`);
