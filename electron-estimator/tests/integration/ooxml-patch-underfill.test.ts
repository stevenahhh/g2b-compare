import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import JSZip from "jszip";
import { expect, it } from "vitest";
import { wantedCells } from "../../src/legacy/inspect/cell-address.js";
import {
  parseWorksheetCells,
  readSharedStrings
} from "../../src/legacy/inspect/cell-values.js";
import { LegacyProfileManifestSchema } from "../../src/legacy/inspect/profile.js";
import { zipText } from "../../src/legacy/inspect/xml.js";
import { patchLegacyWorkbook } from "../../src/legacy/patch/index.js";
import {
  sourcesBySha,
  workbookInventory
} from "./ooxml-patch-helpers.js";

const B_SHA = "2220cd9936ebdf908d64c0571a4c8de83973eaa89c6778a64afec07de7c5e701";

it("clears only owned non-formula cells after B item one", async () => {
  const source = (await sourcesBySha()).get(B_SHA);
  expect(source).toBeDefined();
  if (source === undefined) {
    return;
  }
  const manifestInput: unknown = JSON.parse(await readFile(resolve(
    import.meta.dirname,
    "..",
    "..",
    "resources",
    "manifests",
    "legacy",
    "suncheon-procurement-2025.json"
  ), "utf8"));
  const profile = LegacyProfileManifestSchema.parse(manifestInput);
  const beforeArchive = await JSZip.loadAsync(await readFile(source));
  const beforeInventory = await workbookInventory(beforeArchive);
  const result = await patchLegacyWorkbook({
    source,
    expectedSourceSha256: B_SHA,
    itemCount: 1,
    cells: [
      {
        sheet: "수량산출서",
        address: "B8",
        value: { kind: "text", value: "한 행 한글" }
      },
      {
        sheet: "수량산출서",
        address: "F8",
        value: { kind: "number", value: "2" }
      },
      {
        sheet: "단가조사",
        address: "H5",
        value: { kind: "number", value: "345000" }
      }
    ]
  });
  const afterArchive = await JSZip.loadAsync(result.workbook);
  const afterInventory = await workbookInventory(afterArchive);
  expect(afterInventory.formulas).toEqual(beforeInventory.formulas);
  const owned = new Set(
    [...wantedCells(profile.appOwnedCells)].flatMap(([sheet, points]) =>
      points.map((point) => `${sheet}!${point.address}`)
    )
  );
  expect(result.receipt.changedCells.every(({ sheet, address }) =>
    owned.has(`${sheet}!${address}`)
  )).toBe(true);
  const cleared = result.receipt.changedCells.filter(
    (cell) => cell.after.kind === "blank"
  );
  expect(cleared.length).toBeGreaterThan(0);
  const sharedStrings = await readSharedStrings(afterArchive);
  for (const sheet of profile.sheetMap) {
    const addresses = cleared
      .filter((cell) => cell.sheet === sheet.name)
      .map((cell) => cell.address);
    if (addresses.length === 0) {
      continue;
    }
    const values = parseWorksheetCells({
      wanted: new Set(addresses),
      sharedStrings,
      xml: await zipText(afterArchive, sheet.part)
    });
    addresses.forEach((address) => {
      expect(values.get(address)).toEqual({ kind: "blank" });
    });
  }
}, 30_000);
