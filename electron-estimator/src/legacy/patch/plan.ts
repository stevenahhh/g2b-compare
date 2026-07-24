import {
  parseAddress,
  parseRange,
  parseRowRange,
  wantedCells
} from "../inspect/cell-address.js";
import { LegacyImportError } from "../inspect/errors.js";
import { OoxmlPatchError } from "./errors.js";
import type { PatchProfile } from "./profile.js";
import type { PatchCellInput, PatchCellValue } from "./types.js";

export type PlannedCell = {
  readonly sheet: string;
  readonly address: string;
  readonly value: PatchCellValue;
  readonly explicit: boolean;
  readonly mayClearFormula: boolean;
};

type PlanInput = {
  readonly profile: PatchProfile;
  readonly itemCount: number;
  readonly cells: readonly PatchCellInput[];
};

export function buildPatchPlan(input: PlanInput): readonly PlannedCell[] {
  if (input.itemCount > input.profile.capacity.rows) {
    throw new OoxmlPatchError("PROFILE_CAPACITY_EXCEEDED");
  }
  const owned = wantedCells(input.profile.appOwnedCells);
  const unused = cellKeys(input.profile.ownership.UNUSED_SLOT);
  const positions = slotPositions(input.profile);
  const planned = new Map<string, PlannedCell>();
  for (const cell of input.cells) {
    const key = cellKey(cell.sheet, cell.address);
    if (
      planned.has(key) ||
      !owned.get(cell.sheet)?.some((point) => point.address === cell.address)
    ) {
      throw new OoxmlPatchError(
        planned.has(key) ? "PATCH_VALUE_INVALID" : "OOXML_CELL_NOT_OWNED"
      );
    }
    const position = positions.get(key);
    if (position === undefined) {
      throw new LegacyImportError("STALE_PROFILE");
    }
    if (position > input.itemCount) {
      throw new OoxmlPatchError("PROFILE_CAPACITY_EXCEEDED");
    }
    planned.set(key, {
      ...cell,
      explicit: true,
      mayClearFormula: unused.has(key)
    });
  }
  for (const [sheet, points] of owned) {
    for (const point of points) {
      const key = cellKey(sheet, point.address);
      const position = positions.get(key);
      if (position === undefined) {
        throw new LegacyImportError("STALE_PROFILE");
      }
      if (position > input.itemCount && !planned.has(key)) {
        planned.set(key, {
          sheet,
          address: point.address,
          value: { kind: "blank" },
          explicit: false,
          mayClearFormula: unused.has(key)
        });
      }
    }
  }
  const sheetOrder = new Map(
    input.profile.sheetMap.map((sheet, index) => [sheet.name, index])
  );
  return [...planned.values()].toSorted((left, right) => {
    const sheet = (sheetOrder.get(left.sheet) ?? -1) -
      (sheetOrder.get(right.sheet) ?? -1);
    const leftPoint = parseAddress(left.address);
    const rightPoint = parseAddress(right.address);
    return sheet || leftPoint.row - rightPoint.row ||
      leftPoint.column - rightPoint.column;
  });
}

function slotPositions(profile: PatchProfile): ReadonlyMap<string, number> {
  const rows = new Map<string, ReadonlyMap<number, number>>();
  switch (profile.profileId) {
    case "A": {
      const sheet = parseRange(profile.appOwnedCells[0] ?? "").sheet;
      rows.set(
        sheet,
        new Map(profile.rowMap.itemRows.map((row, index) => [row, index + 1]))
      );
      break;
    }
    case "B":
    case "C": {
      const quantity = parseRowRange(profile.rowMap.quantityRows);
      const prices = parseRowRange(profile.rowMap.priceRows);
      rows.set(
        quantity.sheet,
        new Map(quantity.rows.map((row, index) => [row, index + 1]))
      );
      rows.set(
        prices.sheet,
        new Map(prices.rows.map((row, index) => [row, index + 1]))
      );
      break;
    }
    default:
      assertNever(profile);
  }
  const positions = new Map<string, number>();
  for (const [sheet, points] of wantedCells(profile.appOwnedCells)) {
    const sheetRows = rows.get(sheet);
    for (const point of points) {
      const position = sheetRows?.get(point.row);
      if (position !== undefined) {
        positions.set(cellKey(sheet, point.address), position);
      }
    }
  }
  return positions;
}

function cellKeys(references: readonly string[]): ReadonlySet<string> {
  const keys = new Set<string>();
  for (const [sheet, points] of wantedCells(references)) {
    points.forEach((point) => {
      keys.add(cellKey(sheet, point.address));
    });
  }
  return keys;
}

function cellKey(sheet: string, address: string): string {
  return `${sheet}!${address}`;
}

function assertNever(value: never): never {
  throw new LegacyImportError("STALE_PROFILE");
}
