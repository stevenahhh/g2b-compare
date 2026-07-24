import type { LegacyProfileManifest } from "../inspect/profile.js";
import { wantedCells } from "../inspect/cell-address.js";
import {
  inspectOoxmlPackage,
  type OoxmlInspection
} from "../inspect/ooxml.js";
import {
  inspectZipPackage,
  type InspectedZipPackage
} from "../inspect/zip.js";
import {
  diffSemanticCells,
  type SemanticCellChange
} from "./cells.js";
import {
  cacheInventoryChanged,
  definedNamesChanged,
  externalLinksChanged,
  formulaInventoryChanged,
  packageChanges,
  sheetStructureChanged,
  vbaChanged,
  warningCounts,
  type WarningCounts
} from "./inventory.js";
import {
  VALIDATION_ERROR_CODES,
  type PatchCellReference,
  type PatchReceiptContract,
  type ValidationErrorCode
} from "./types.js";

export type ValidationPackagePair = {
  readonly originalZip: InspectedZipPackage;
  readonly outputZip: InspectedZipPackage;
  readonly originalOoxml: OoxmlInspection;
  readonly outputOoxml: OoxmlInspection;
};

export type DriftAnalysis = {
  readonly errors: readonly ValidationErrorCode[];
  readonly changedCells: readonly SemanticCellChange[];
  readonly warnings: WarningCounts;
};

export async function inspectPackagePair(
  originalBytes: Uint8Array,
  outputBytes: Uint8Array
): Promise<ValidationPackagePair> {
  const originalZip = await inspectZipPackage(originalBytes);
  const outputZip = await inspectZipPackage(outputBytes);
  const originalOoxml = await inspectOoxmlPackage(originalZip);
  const outputOoxml = await inspectOoxmlPackage(outputZip);
  return { originalZip, outputZip, originalOoxml, outputOoxml };
}

export function manifestMatchesOriginal(
  manifest: LegacyProfileManifest,
  pair: ValidationPackagePair
): boolean {
  return (
    same(manifest.source.packageParts, pair.originalOoxml.packageParts) &&
    same(manifest.sheetMap, pair.originalOoxml.sheetMap) &&
    same(manifest.baselineInventory, pair.originalOoxml.baselineInventory)
  );
}

export async function analyzeDrift(
  manifest: LegacyProfileManifest,
  receipt: PatchReceiptContract,
  pair: ValidationPackagePair
): Promise<DriftAnalysis> {
  const errors = new Set<ValidationErrorCode>();
  const changedParts = packageChanges(pair.originalZip, pair.outputZip);
  compareReceiptSet(
    changedParts,
    receipt.changedParts,
    "UNEXPECTED_PART_DRIFT",
    errors
  );
  if (vbaChanged(pair.originalZip, pair.outputZip)) {
    errors.add("UNEXPECTED_VBA_DRIFT");
  }
  const changedCells = await diffSemanticCells(
    pair.originalZip.archive,
    pair.outputZip.archive,
    pair.originalOoxml.resolvedSheets,
    pair.outputOoxml.resolvedSheets
  );
  const actualCells = changedCells.map(referenceKey);
  const receiptCells = [
    ...receipt.changedCells,
    ...(receipt.affectedFormulaCells ?? [])
  ].map(referenceKey);
  if (!sameSet(actualCells, receiptCells)) {
    errors.add("PATCH_RECEIPT_MISMATCH");
  }
  const appOwned = appOwnedCells(manifest);
  const cacheCells = new Set(
    (receipt.affectedFormulaCells ?? []).map(referenceKey)
  );
  if (
    changedCells.some(
      (cell) =>
        !appOwned.has(referenceKey(cell)) &&
        !cacheCells.has(referenceKey(cell))
    )
  ) {
    errors.add("UNEXPECTED_CELL_DRIFT");
  }
  const formulaCells = new Set((receipt.formulaCells ?? []).map(referenceKey));
  if (
    changedCells.some(
      (cell) => cell.formulaChanged && !formulaCells.has(referenceKey(cell))
    ) ||
    formulaInventoryChanged(manifest, pair.outputOoxml)
  ) {
    errors.add("UNEXPECTED_FORMULA_DRIFT");
  }
  if (
    changedCells.some(
      (cell) => cell.cacheChanged && !cacheCells.has(referenceKey(cell))
    ) ||
    cacheInventoryChanged(manifest, pair.outputOoxml)
  ) {
    errors.add("UNEXPECTED_CACHE_DRIFT");
  }
  if (sheetStructureChanged(manifest, pair.outputOoxml)) {
    errors.add("UNEXPECTED_SHEET_STRUCTURE_DRIFT");
  }
  if (externalLinksChanged(manifest, pair.outputOoxml)) {
    errors.add("NEW_EXTERNAL_LINK");
  }
  if (definedNamesChanged(manifest, pair.outputOoxml)) {
    errors.add("UNEXPECTED_DEFINED_NAME_DRIFT");
  }
  return {
    errors: VALIDATION_ERROR_CODES.filter((code) => errors.has(code)),
    changedCells,
    warnings: warningCounts(manifest, pair.outputOoxml)
  };
}

function compareReceiptSet(
  actual: readonly string[],
  expected: readonly string[],
  unexpectedCode: ValidationErrorCode,
  errors: Set<ValidationErrorCode>
): void {
  if (!sameSet(actual, expected)) {
    errors.add("PATCH_RECEIPT_MISMATCH");
  }
  const expectedSet = new Set(expected);
  if (actual.some((item) => !expectedSet.has(item))) {
    errors.add(unexpectedCode);
  }
}

function appOwnedCells(manifest: LegacyProfileManifest): ReadonlySet<string> {
  const cells = wantedCells(manifest.appOwnedCells);
  return new Set(
    [...cells].flatMap(([sheet, points]) =>
      points.map(({ address }) => `${sheet}!${address}`)
    )
  );
}

function referenceKey(reference: PatchCellReference): string {
  return `${reference.sheet}!${reference.address}`;
}

function sameSet(left: readonly string[], right: readonly string[]): boolean {
  return same([...new Set(left)].toSorted(), [...new Set(right)].toSorted());
}

function same(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}
