import {
  parseAddress,
  parseRange,
  parseRowRange
} from "./cell-address.js";
import { LegacyImportError } from "./errors.js";
import type { LegacyProfileManifest } from "./profile.js";
import type { LegacyCellDto, LegacyItemDto } from "./types.js";

export function buildItems(
  profile: LegacyProfileManifest,
  cells: readonly LegacyCellDto[]
): readonly LegacyItemDto[] {
  switch (profile.profileId) {
    case "A": {
      const itemSheet = parseRange(profile.appOwnedCells[0] ?? "").sheet;
      return profile.rowMap.itemRows.map((row, index) =>
        itemFromCells(cells, {
          position: index + 1,
          sourceRow: row,
          quoteRow: null,
          itemSheet,
          itemNameColumn: "C",
          specificationColumn: "D",
          unitColumn: "E"
        })
      );
    }
    case "B":
    case "C": {
      const quantity = parseRowRange(profile.rowMap.quantityRows);
      const prices = parseRowRange(profile.rowMap.priceRows);
      if (
        quantity.rows.length !== profile.capacity.rows ||
        prices.rows.length !== profile.capacity.rows
      ) {
        throw new LegacyImportError("STALE_PROFILE");
      }
      return quantity.rows.map((row, index) =>
        itemFromCells(cells, {
          position: index + 1,
          sourceRow: row,
          quoteRow: prices.rows[index] ?? 0,
          itemSheet: quantity.sheet,
          itemNameColumn: "B",
          specificationColumn: "C",
          unitColumn: "D",
          quoteSheet: prices.sheet
        })
      );
    }
    default:
      return assertNever(profile);
  }
}

type ItemCoordinates = {
  readonly position: number;
  readonly sourceRow: number;
  readonly quoteRow: number | null;
  readonly itemSheet: string;
  readonly itemNameColumn: string;
  readonly specificationColumn: string;
  readonly unitColumn: string;
  readonly quoteSheet?: string;
};

function itemFromCells(
  cells: readonly LegacyCellDto[],
  coordinates: ItemCoordinates
): LegacyItemDto {
  const itemCells = cells.filter((cell) => {
    const point = parseAddress(cell.address);
    return (
      (cell.sheet === coordinates.itemSheet &&
        point.row === coordinates.sourceRow) ||
      (coordinates.quoteSheet !== undefined &&
        cell.sheet === coordinates.quoteSheet &&
        point.row === coordinates.quoteRow)
    );
  });
  return {
    position: coordinates.position,
    sourceRow: coordinates.sourceRow,
    quoteRow: coordinates.quoteRow,
    itemName: requiredText(
      itemCells,
      `${coordinates.itemNameColumn}${coordinates.sourceRow}`
    ),
    specification: requiredText(
      itemCells,
      `${coordinates.specificationColumn}${coordinates.sourceRow}`
    ),
    unit: requiredText(
      itemCells,
      `${coordinates.unitColumn}${coordinates.sourceRow}`
    ),
    cells: itemCells
  };
}

function requiredText(cells: readonly LegacyCellDto[], address: string): string {
  const value = cells.find((cell) => cell.address === address)?.value;
  if (value?.kind === "text" || value?.kind === "number") {
    return value.value;
  }
  throw new LegacyImportError("CORRUPT_OOXML");
}

function assertNever(value: never): never {
  throw new LegacyImportError("STALE_PROFILE");
}
