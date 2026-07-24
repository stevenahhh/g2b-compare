import { rm, readdir } from "node:fs/promises";
import { afterEach, describe, expect, it } from "vitest";
import { recoverInterruptedExports } from "../../src/legacy/export/index.js";
import {
  removeTemporaryDirectory,
  journalRootFor,
  temporaryExportDirectory
} from "./atomic-export-fixtures.js";
import { killBetweenRenames } from "./atomic-export-crash-helpers.js";

const directories: string[] = [];
const journalRoots: string[] = [];

afterEach(async () => {
  await Promise.all(directories.splice(0).map(removeTemporaryDirectory));
  await Promise.all(
    journalRoots.splice(0).map((path) =>
      rm(path, { recursive: true, force: true })
    )
  );
});

describe("atomic legacy export crash consistency", () => {
  it("never exposes a final workbook before its final report", async () => {
    const directory = await temporaryExportDirectory();
    const journalRoot = journalRootFor(directory);
    directories.push(directory);
    journalRoots.push(journalRoot);
    await killBetweenRenames(directory, journalRoot);

    const files = await readdir(directory);
    expect(files.filter((name) => name.endsWith(".xlsx"))).toEqual([]);
    expect(
      files.filter((name) => name.endsWith(".validation.json"))
    ).toHaveLength(1);

    const recovered = await recoverInterruptedExports({ journalRoot });

    expect(recovered).toMatchObject({
      ok: true,
      receipt: {
        scannedTransactions: 1,
        recoveredTransactions: 1,
        cleanupComplete: true
      }
    });
    expect((await readdir(directory)).toSorted()).toEqual([
      "killed-A_검토초안_미재계산.validation.json",
      "killed-A_검토초안_미재계산.xlsx"
    ]);
    expect(await readdir(journalRoot)).toEqual([]);
  }, 60_000);
});
