import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { importLegacyWorkbook } from "../../src/legacy/import.js";

const DATASET = resolve(import.meta.dirname, "..", "..", "..", "dataset");
const EXPECTED = [
  {
    id: "A",
    sha256: "445012e259ab5318a1d52468cce93ee28a55a8bcb467876f40a47a939e4668db",
    capacity: 16,
    members: 46,
    externalLinks: 0,
    firstItem: "영상감시장치",
    lastItem: "정보통신공사"
  },
  {
    id: "B",
    sha256: "2220cd9936ebdf908d64c0571a4c8de83973eaa89c6778a64afec07de7c5e701",
    capacity: 9,
    members: 850,
    externalLinks: 319,
    firstItem: "영상감시장치",
    lastItem: "정보통신공사"
  },
  {
    id: "C",
    sha256: "8a55700bdaf62a00c208c7286531fd56ca321571f73f7620505a823ef5d4d0f1",
    capacity: 24,
    members: 601,
    externalLinks: 253,
    firstItem: "영상감시장치",
    lastItem: "네트워크시스템장비용랙"
  }
] as const;

async function sourcesBySha(): Promise<ReadonlyMap<string, string>> {
  const sources = new Map<string, string>();
  for (const filename of await readdir(DATASET)) {
    if (!filename.toLowerCase().endsWith(".xlsx") || filename.startsWith("~$")) {
      continue;
    }
    const path = resolve(DATASET, filename);
    const bytes = await readFile(path);
    sources.set(createHash("sha256").update(bytes).digest("hex"), path);
  }
  return sources;
}

describe("legacy workbook import", () => {
  it("returns deterministic profile, items, inventory, and member hashes for A/B/C", async () => {
    const sources = await sourcesBySha();

    for (const expected of EXPECTED) {
      const source = sources.get(expected.sha256);
      expect(source).toBeDefined();
      if (source === undefined) {
        continue;
      }
      const before = createHash("sha256").update(await readFile(source)).digest("hex");
      const first = await importLegacyWorkbook(source);
      const second = await importLegacyWorkbook(source);
      const after = createHash("sha256").update(await readFile(source)).digest("hex");

      expect(first.profileId).toBe(expected.id);
      expect(first.sourceSha256).toBe(expected.sha256);
      expect(first.capacity).toBe(expected.capacity);
      expect(first.items).toHaveLength(expected.capacity);
      expect(first.items[0]?.itemName).toBe(expected.firstItem);
      expect(first.items.at(-1)?.itemName).toBe(expected.lastItem);
      expect(first.baselineInventory.externalLinks.count).toBe(expected.externalLinks);
      expect(first.package.memberCount).toBe(expected.members);
      expect(Object.keys(first.package.memberSha256)).toHaveLength(expected.members);
      expect(Object.keys(first.package.memberSha256)).toEqual(
        Object.keys(first.package.memberSha256).toSorted()
      );
      expect(JSON.stringify(first)).toBe(JSON.stringify(second));
      expect(after).toBe(before);
      expect(after).toBe(expected.sha256);
      expect(JSON.stringify(first)).not.toContain(DATASET);
    }
  }, 30_000);

  it("keeps workbook formula text as untrusted data and never evaluates it", async () => {
    const source = (await sourcesBySha()).get(EXPECTED[1].sha256);
    expect(source).toBeDefined();
    if (source === undefined) {
      return;
    }

    const imported = await importLegacyWorkbook(source);
    const formulaCell = imported.items
      .flatMap((item) => item.cells)
      .find((cell) => cell.address === "L11");

    expect(formulaCell?.value).toEqual({
      kind: "formula",
      untrustedFormula: "H11",
      cached: { kind: "number", value: "22067190" }
    });
  });
});
