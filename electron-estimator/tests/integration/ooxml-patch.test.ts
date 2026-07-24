import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import JSZip from "jszip";
import { describe, expect, it } from "vitest";
import {
  patchLegacyWorkbook,
  type PatchCellInput
} from "../../src/legacy/patch/index.js";
import { importLegacyWorkbook } from "../../src/legacy/import.js";
import {
  parseWorksheetCells,
  readSharedStrings
} from "../../src/legacy/inspect/cell-values.js";
import { LegacyProfileManifestSchema } from "../../src/legacy/inspect/profile.js";
import { zipText } from "../../src/legacy/inspect/xml.js";
import {
  calcMetadata,
  changedPackageParts,
  packageHashes,
  sourcesBySha,
  workbookInventory
} from "./ooxml-patch-helpers.js";
const CASES = [
  {
    profileId: "A",
    manifest: "gwangyang-direct-2025.json",
    sha256: "445012e259ab5318a1d52468cce93ee28a55a8bcb467876f40a47a939e4668db",
    itemCount: 16,
    expectedOrder: ["자재내역서!C9", "자재내역서!F9", "자재내역서!G9"],
    cells: [
      { sheet: "자재내역서", address: "G9", value: { kind: "number", value: "987654" } },
      { sheet: "자재내역서", address: "C9", value: { kind: "text", value: "한글 <&> =SUM(A1)" } },
      { sheet: "자재내역서", address: "F9", value: { kind: "number", value: "3.5" } }
    ]
  },
  {
    profileId: "B",
    manifest: "suncheon-procurement-2025.json",
    sha256: "2220cd9936ebdf908d64c0571a4c8de83973eaa89c6778a64afec07de7c5e701",
    itemCount: 9,
    expectedOrder: ["수량산출서!B8", "수량산출서!F8", "단가조사!H5"],
    cells: [
      { sheet: "단가조사", address: "H5", value: { kind: "number", value: "987654" } },
      { sheet: "수량산출서", address: "B8", value: { kind: "text", value: "한글 <&> +SUM(A1)" } },
      { sheet: "수량산출서", address: "F8", value: { kind: "number", value: "3.5" } }
    ]
  },
  {
    profileId: "C",
    manifest: "gwangyang-procurement-final-2025.json",
    sha256: "8a55700bdaf62a00c208c7286531fd56ca321571f73f7620505a823ef5d4d0f1",
    itemCount: 24,
    expectedOrder: ["수량산출서!B6", "수량산출서!F6", "단가조사!H5"],
    cells: [
      { sheet: "단가조사", address: "H5", value: { kind: "number", value: "987654" } },
      { sheet: "수량산출서", address: "B6", value: { kind: "text", value: "한글 <&> @SUM(A1)" } },
      { sheet: "수량산출서", address: "F6", value: { kind: "number", value: "3.5" } }
    ]
  }
] as const satisfies readonly {
  readonly profileId: "A" | "B" | "C";
  readonly manifest: string;
  readonly sha256: string;
  readonly itemCount: number;
  readonly expectedOrder: readonly string[];
  readonly cells: readonly PatchCellInput[];
}[];

describe("allowlisted OOXML patching", () => {
  it("patches one Korean text, quantity, and price in every exact legacy profile", async () => {
    const sources = await sourcesBySha();
    for (const fixture of CASES) {
      const source = sources.get(fixture.sha256);
      expect(source).toBeDefined();
      if (source === undefined) {
        continue;
      }
      const beforeBytes = await readFile(source);
      const profileInput: unknown = JSON.parse(await readFile(resolve(
        import.meta.dirname,
        "..",
        "..",
        "resources",
        "manifests",
        "legacy",
        fixture.manifest
      ), "utf8"));
      const profile = LegacyProfileManifestSchema.parse(profileInput);
      const partsBySheet = new Map(
        profile.sheetMap.map((sheet) => [sheet.name, sheet.part])
      );
      const beforeArchive = await JSZip.loadAsync(beforeBytes);
      const beforeInventory = await workbookInventory(beforeArchive);
      const beforeHashes = await packageHashes(beforeArchive);

      const first = await patchLegacyWorkbook({
        source,
        expectedSourceSha256: fixture.sha256,
        itemCount: fixture.itemCount,
        cells: fixture.cells
      });
      const second = await patchLegacyWorkbook({
        source,
        expectedSourceSha256: fixture.sha256,
        itemCount: fixture.itemCount,
        cells: fixture.cells.toReversed()
      });
      const afterArchive = await JSZip.loadAsync(first.workbook);
      const afterInventory = await workbookInventory(afterArchive);
      const afterHashes = await packageHashes(afterArchive);
      const metadata = await calcMetadata(afterArchive);

      expect(first.receipt.profileId).toBe(fixture.profileId);
      expect(first.receipt.sourceSha256).toBe(fixture.sha256);
      expect(first.receipt.changedCells.map(({ sheet, address }) => `${sheet}!${address}`))
        .toEqual(fixture.expectedOrder);
      expect(first.receipt).toEqual(second.receipt);
      expect(createHash("sha256").update(first.workbook).digest("hex")).toBe(
        createHash("sha256").update(second.workbook).digest("hex")
      );
      expect(afterInventory.dimensions).toEqual(beforeInventory.dimensions);
      expect(afterInventory.merges).toEqual(beforeInventory.merges);
      expect(afterInventory.formulas).toEqual(beforeInventory.formulas);
      expect([...afterInventory.styles]).toEqual([...beforeInventory.styles]);
      const removedCaches = [...beforeInventory.formulaCaches]
        .filter((cell) => !afterInventory.formulaCaches.has(cell))
        .toSorted();
      expect(first.receipt.affectedFormulaCells.map(({ sheet, address }) =>
        `${partsBySheet.get(sheet)}!${address}`
      ).toSorted()).toEqual(removedCaches);
      expect([...afterInventory.formulaCaches]
        .filter((cell) => !beforeInventory.formulaCaches.has(cell)))
        .toEqual([]);
      expect(changedPackageParts(beforeHashes, afterHashes))
        .toEqual(first.receipt.changedParts);
      expect(first.receipt.changedParts.every((part) =>
        part.startsWith("xl/worksheets/") ||
        [
          "[Content_Types].xml",
          "xl/_rels/workbook.xml.rels",
          "xl/calcChain.xml",
          "xl/workbook.xml"
        ].includes(part)
      )).toBe(true);
      expect(metadata.calcChainRelationships).toBe(0);
      expect(metadata.calcChainOverrides).toBe(0);
      expect(Object.fromEntries(metadata.calcProperties)).toMatchObject({
        calcMode: "auto",
        calcOnSave: "1",
        forceFullCalc: "1",
        fullCalcOnLoad: "1"
      });
      expect(afterArchive.file("xl/calcChain.xml")).toBeNull();
      const textInput = fixture.cells.find((cell) => cell.value.kind === "text");
      expect(textInput).toBeDefined();
      if (textInput !== undefined && textInput.value.kind === "text") {
        const part = partsBySheet.get(textInput.sheet);
        expect(part).toBeDefined();
        if (part !== undefined) {
          const parsedCells = parseWorksheetCells({
            wanted: new Set([textInput.address]),
            sharedStrings: await readSharedStrings(afterArchive),
            xml: await zipText(afterArchive, part)
          });
          expect(parsedCells.get(textInput.address)).toEqual(textInput.value);
        }
      }
      if (fixture.profileId === "C") {
        expect(afterInventory.formulas.filter((formula) =>
          /sheet10\.xml!U1[3-7]=/u.test(formula)
        )).toEqual([
          "xl/worksheets/sheet10.xml!U13=단가조사!F18",
          "xl/worksheets/sheet10.xml!U14=단가조사!F19",
          "xl/worksheets/sheet10.xml!U15=단가조사!F20",
          "xl/worksheets/sheet10.xml!U16=단가조사!F21",
          "xl/worksheets/sheet10.xml!U17=단가조사!F22"
        ]);
      }
      expect(createHash("sha256").update(await readFile(source)).digest("hex"))
        .toBe(fixture.sha256);
    }
  }, 60_000);

  it("returns the exact source bytes and an empty receipt for baseline values", async () => {
    const sources = await sourcesBySha();
    for (const fixture of CASES) {
      const source = sources.get(fixture.sha256);
      expect(source).toBeDefined();
      if (source === undefined) {
        continue;
      }
      const imported = await importLegacyWorkbook(source);
      const cells = fixture.cells.map(({ sheet, address }) => {
        const current = imported.items
          .flatMap((item) => item.cells)
          .find((cell) => cell.sheet === sheet && cell.address === address)?.value;
        expect(current?.kind === "text" || current?.kind === "number").toBe(true);
        if (current?.kind !== "text" && current?.kind !== "number") {
          throw new TypeError("baseline scalar missing");
        }
        return { sheet, address, value: current };
      });
      const before = await readFile(source);
      const result = await patchLegacyWorkbook({
        source,
        expectedSourceSha256: fixture.sha256,
        itemCount: fixture.itemCount,
        cells
      });
      expect(result.receipt.changedCells).toEqual([]);
      expect(result.receipt.affectedFormulaCells).toEqual([]);
      expect(result.receipt.changedParts).toEqual([]);
      expect(result.workbook).toEqual(new Uint8Array(before));
    }
  }, 30_000);
});
