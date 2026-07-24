import { LegacyImportError } from "./errors.js";

export type CellPoint = {
  readonly address: string;
  readonly column: number;
  readonly row: number;
};

export type CellRange = {
  readonly sheet: string;
  readonly start: CellPoint;
  readonly end: CellPoint;
};

export function wantedCells(
  references: readonly string[]
): ReadonlyMap<string, readonly CellPoint[]> {
  const bySheet = new Map<string, Map<string, CellPoint>>();
  for (const reference of references) {
    const range = parseRange(reference);
    const points = bySheet.get(range.sheet) ?? new Map<string, CellPoint>();
    for (let row = range.start.row; row <= range.end.row; row += 1) {
      for (
        let column = range.start.column;
        column <= range.end.column;
        column += 1
      ) {
        const point = {
          address: `${columnName(column)}${row}`,
          column,
          row
        };
        points.set(point.address, point);
      }
    }
    bySheet.set(range.sheet, points);
  }
  return new Map(
    [...bySheet].map(([sheet, points]) => [
      sheet,
      [...points.values()].toSorted(
        (left, right) => left.row - right.row || left.column - right.column
      )
    ])
  );
}

export function parseRange(reference: string): CellRange {
  const separator = reference.lastIndexOf("!");
  const sheet = reference.slice(0, separator);
  const bounds = reference.slice(separator + 1).split(":");
  const start = parseAddress(bounds[0] ?? "");
  const end = parseAddress(bounds[1] ?? bounds[0] ?? "");
  if (
    sheet.length === 0 ||
    start.row > end.row ||
    start.column > end.column
  ) {
    throw new LegacyImportError("STALE_PROFILE");
  }
  return { sheet, start, end };
}

export function parseAddress(address: string): CellPoint {
  let split = 0;
  while (split < address.length) {
    const character = address[split];
    if (
      character === undefined ||
      character < "A" ||
      character > "Z"
    ) {
      break;
    }
    split += 1;
  }
  const letters = address.slice(0, split);
  const rowText = address.slice(split);
  const row = Number(rowText);
  if (
    letters.length === 0 ||
    !Number.isInteger(row) ||
    row < 1 ||
    [...rowText].some((character) => character < "0" || character > "9")
  ) {
    throw new LegacyImportError("STALE_PROFILE");
  }
  const column = [...letters].reduce(
    (value, character) => value * 26 + character.charCodeAt(0) - 64,
    0
  );
  return { address, column, row };
}

export function parseRowRange(reference: string): {
  readonly sheet: string;
  readonly rows: readonly number[];
} {
  const separator = reference.lastIndexOf("!");
  const sheet = reference.slice(0, separator);
  const bounds = reference.slice(separator + 1).split(":");
  const start = Number(bounds[0]);
  const end = Number(bounds[1] ?? bounds[0]);
  if (
    sheet.length === 0 ||
    !Number.isInteger(start) ||
    !Number.isInteger(end) ||
    start < 1 ||
    end < start
  ) {
    throw new LegacyImportError("STALE_PROFILE");
  }
  return {
    sheet,
    rows: Array.from({ length: end - start + 1 }, (_, index) => start + index)
  };
}

function columnName(column: number): string {
  let value = column;
  let name = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    name = String.fromCharCode(65 + remainder) + name;
    value = Math.floor((value - 1) / 26);
  }
  return name;
}
