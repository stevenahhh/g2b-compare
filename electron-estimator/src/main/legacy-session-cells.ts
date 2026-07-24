import type {
  LegacyCellValue,
  LegacyImportDto
} from "../legacy/import.js";
import type { PatchCellInput } from "../legacy/patch/types.js";
import type { LegacyEditableCell } from "../workflows/legacy/contracts.js";

export function editableCells(
  imported: LegacyImportDto
): readonly LegacyEditableCell[] {
  return imported.items.flatMap((item) =>
    item.cells.flatMap((cell) => {
      if (generatedCell(imported.profileId, cell.address)) {
        return [];
      }
      const value = editableValue(cell.value);
      return value === null
        ? []
        : [{
            position: item.position,
            sheet: cell.sheet,
            address: cell.address,
            label: `${cell.sheet} ${cell.address}`,
            value
          }];
    })
  );
}

export function sameCellKeys(
  expected: readonly LegacyEditableCell[],
  actual: readonly PatchCellInput[]
): boolean {
  const expectedKeys = expected.map(cellKey).toSorted();
  const actualKeys = actual.map(cellKey).toSorted();
  return expectedKeys.length === actualKeys.length &&
    expectedKeys.every((key, index) => key === actualKeys[index]);
}

export function hasMissingComparison(
  cells: readonly PatchCellInput[]
): boolean {
  const required = new Set(["H", "L", "P"]);
  const comparisons = cells
    .filter((cell) => cell.sheet === "단가조사")
    .filter((cell) => required.has(cell.address.replace(/\d+$/u, "")));
  return comparisons.some((cell) =>
    cell.value.kind !== "number" || Number(cell.value.value) <= 0
  );
}

function editableValue(
  value: LegacyCellValue
): LegacyEditableCell["value"] | null {
  return value.kind === "blank" ||
    value.kind === "text" ||
    value.kind === "number"
    ? value
    : null;
}

function generatedCell(profile: "A" | "B" | "C", address: string): boolean {
  const column = address.replace(/\d+$/u, "");
  return profile === "A" ? column === "B" : column === "A";
}

function cellKey(cell: { readonly sheet: string; readonly address: string }): string {
  return `${cell.sheet}!${cell.address}`;
}
