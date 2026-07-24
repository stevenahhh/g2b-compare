import { createHash } from "node:crypto";
import {
  mkdtemp,
  readFile,
  readdir,
  rm,
  writeFile
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { LegacyImportError } from "../../src/legacy/import.js";
import { ZIP_LIMITS } from "../../src/legacy/inspect/zip.js";
import {
  OoxmlPatchError,
  patchLegacyWorkbook
} from "../../src/legacy/patch/index.js";

const DATASET = resolve(import.meta.dirname, "..", "..", "..", "dataset");
const C_SHA = "8a55700bdaf62a00c208c7286531fd56ca321571f73f7620505a823ef5d4d0f1";

async function sourceBySha(sha256: string): Promise<string> {
  for (const filename of await readdir(DATASET)) {
    const path = resolve(DATASET, filename);
    const bytes = await readFile(path);
    if (createHash("sha256").update(bytes).digest("hex") === sha256) {
      return path;
    }
  }
  throw new TypeError("fixture source missing");
}

function hasCode(code: string): (error: unknown) => boolean {
  return (error) => error instanceof OoxmlPatchError && error.code === code;
}

describe("OOXML patch rejection", () => {
  it("rejects unowned cells and capacity overflow without changing source", async () => {
    const source = await sourceBySha(C_SHA);
    const before = createHash("sha256").update(await readFile(source)).digest("hex");

    await expect(patchLegacyWorkbook({
      source,
      expectedSourceSha256: C_SHA,
      itemCount: 24,
      cells: [
        {
          sheet: "원가",
          address: "A1",
          value: { kind: "text", value: "not owned" }
        }
      ]
    })).rejects.toSatisfy(hasCode("OOXML_CELL_NOT_OWNED"));

    await expect(patchLegacyWorkbook({
      source,
      expectedSourceSha256: C_SHA,
      itemCount: 25,
      cells: []
    })).rejects.toSatisfy(hasCode("PROFILE_CAPACITY_EXCEEDED"));

    expect(createHash("sha256").update(await readFile(source)).digest("hex"))
      .toBe(before);
  });

  it("rejects stale source, malformed values, and importer ZIP limits", async () => {
    const source = await sourceBySha(C_SHA);
    await expect(patchLegacyWorkbook({
      source,
      expectedSourceSha256: "0".repeat(64),
      itemCount: 24,
      cells: []
    })).rejects.toSatisfy(hasCode("STALE_SOURCE"));
    await expect(patchLegacyWorkbook({
      source,
      expectedSourceSha256: C_SHA,
      itemCount: 24,
      cells: [{
        sheet: "수량산출서",
        address: "F6",
        value: { kind: "number", value: "1e3" }
      }]
    })).rejects.toSatisfy(hasCode("PATCH_VALUE_INVALID"));

    const scratch = await mkdtemp(join(tmpdir(), "ooxml-patch-limit-"));
    const oversized = resolve(scratch, "oversized.xlsx");
    try {
      await writeFile(
        oversized,
        Buffer.alloc(ZIP_LIMITS.maxSourceBytes + 1)
      );
      await expect(patchLegacyWorkbook({
        source: oversized,
        expectedSourceSha256: C_SHA,
        itemCount: 24,
        cells: []
      })).rejects.toSatisfy((error: unknown) =>
        error instanceof LegacyImportError &&
        error.code === "ZIP_LIMIT_EXCEEDED"
      );
      expect(await readdir(scratch)).toEqual(["oversized.xlsx"]);
    } finally {
      await rm(scratch, { recursive: true });
    }
  });
});
