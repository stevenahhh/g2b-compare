import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const matrixPath = resolve(process.cwd(), "..", "docs", "tauri-parity-matrix.md");

const requiredIds = [
  ...range("SHELL", 8),
  ...range("CAT", 17),
  ...range("EST", 18),
  ...range("DATA", 7),
  ...range("OFF", 9),
  ...range("DB", 6),
  ...range("PKG", 5),
];

describe("desktop parity matrix", () => {
  const rows = readRows(readFileSync(matrixPath, "utf8"));

  it("contains every immutable contract exactly once", () => {
    const ids = rows.map(([id]) => id);

    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.toSorted()).toEqual(requiredIds.toSorted());
  });

  it("names every implementation and evidence seam", () => {
    for (const [id, ...fields] of rows) {
      expect(fields, `${id} must have five contract fields`).toHaveLength(5);
      for (const field of fields) {
        expect(field, `${id} contains an empty contract field`).not.toBe("");
      }
    }
  });
});

function range(prefix: string, count: number): string[] {
  return Array.from(
    { length: count },
    (_, index) => `${prefix}-${String(index + 1).padStart(3, "0")}`,
  );
}

function readRows(markdown: string): string[][] {
  return markdown
    .split(/\r?\n/u)
    .filter((line) =>
      /^\| (?:SHELL|CAT|EST|DATA|OFF|DB|PKG)-\d{3} \|/u.test(line),
    )
    .map((line) =>
      line
        .split("|")
        .slice(1, -1)
        .map((field) => field.trim()),
    );
}
