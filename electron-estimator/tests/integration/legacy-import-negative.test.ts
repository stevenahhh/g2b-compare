import { createHash } from "node:crypto";
import { readFile, readdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import JSZip from "jszip";
import { describe, expect, it } from "vitest";
import {
  importLegacyWorkbook,
  LegacyImportError
} from "../../src/legacy/import.js";
import {
  inspectZipPackage,
  ZIP_LIMITS
} from "../../src/legacy/inspect/zip.js";
import { inspectOoxmlPackage } from "../../src/legacy/inspect/ooxml.js";
import {
  assertProfileMatchesInspection,
  LegacyProfileManifestSchema
} from "../../src/legacy/inspect/profile.js";

const DATASET = resolve(import.meta.dirname, "..", "..", "..", "dataset");

async function zipBytes(
  name: string,
  content = "safe"
): Promise<Uint8Array> {
  const zip = new JSZip();
  zip.file(name, content);
  return zip.generateAsync({ type: "uint8array", compression: "STORE" });
}

function expectCode(code: string): (error: unknown) => boolean {
  return (error) =>
    error instanceof LegacyImportError &&
    error.code === code &&
    !error.message.includes("\\") &&
    error.stack === undefined;
}

function replaceAllBytes(
  source: Uint8Array,
  before: string,
  after: string
): Uint8Array {
  expect(after.length).toBe(before.length);
  const changed = Buffer.from(source);
  const needle = Buffer.from(before, "utf8");
  const replacement = Buffer.from(after, "utf8");
  let offset = changed.indexOf(needle);
  while (offset >= 0) {
    replacement.copy(changed, offset);
    offset = changed.indexOf(needle, offset + replacement.length);
  }
  return changed;
}

function findSignature(bytes: Uint8Array, signature: number): number {
  const buffer = Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  for (let offset = 0; offset <= buffer.length - 4; offset += 1) {
    if (buffer.readUInt32LE(offset) === signature) {
      return offset;
    }
  }
  return -1;
}

describe("legacy ZIP rejection", () => {
  it("rejects an unknown workbook SHA before importing it", async () => {
    const path = resolve(import.meta.dirname, ".legacy-import-unknown.xlsx");
    try {
      await writeFile(path, await zipBytes("[Content_Types].xml", "unknown"));
      await expect(importLegacyWorkbook(path)).rejects.toSatisfy(
        expectCode("UNSUPPORTED_WORKBOOK")
      );
    } finally {
      await import("node:fs/promises").then(({ rm }) => rm(path, { force: true }));
    }
  });

  it("rejects corrupt OOXML and CRC mismatches", async () => {
    await expect(inspectZipPackage(Buffer.from("not-a-zip"))).rejects.toSatisfy(
      expectCode("CORRUPT_OOXML")
    );

    const corruptCrc = Buffer.from(await zipBytes("safe.txt", "payload"));
    const local = findSignature(corruptCrc, 0x04034b50);
    expect(local).toBeGreaterThanOrEqual(0);
    const nameLength = corruptCrc.readUInt16LE(local + 26);
    const extraLength = corruptCrc.readUInt16LE(local + 28);
    const contentOffset = local + 30 + nameLength + extraLength;
    corruptCrc.writeUInt8(
      corruptCrc.readUInt8(contentOffset) ^ 0xff,
      contentOffset
    );
    await expect(inspectZipPackage(corruptCrc)).rejects.toSatisfy(
      expectCode("CORRUPT_OOXML")
    );
  });

  it("rejects duplicate and traversal member names before JSZip loads them", async () => {
    const duplicateZip = new JSZip();
    duplicateZip.file("a.txt", "first");
    duplicateZip.file("b.txt", "second");
    const duplicate = replaceAllBytes(
      await duplicateZip.generateAsync({
        type: "uint8array",
        compression: "STORE"
      }),
      "b.txt",
      "a.txt"
    );
    await expect(inspectZipPackage(duplicate)).rejects.toSatisfy(
      expectCode("UNSAFE_ZIP_ENTRY")
    );

    const traversal = await zipBytes("../evil.txt");
    await expect(inspectZipPackage(traversal)).rejects.toSatisfy(
      expectCode("UNSAFE_ZIP_ENTRY")
    );
  });

  it("rejects declared ZIP bombs and misleading central-directory counts", async () => {
    const bomb = Buffer.from(await zipBytes("safe.txt"));
    const central = findSignature(bomb, 0x02014b50);
    const local = findSignature(bomb, 0x04034b50);
    expect(central).toBeGreaterThanOrEqual(0);
    expect(local).toBeGreaterThanOrEqual(0);
    const oversized = ZIP_LIMITS.maxMemberUncompressedBytes + 1;
    bomb.writeUInt32LE(oversized, central + 24);
    bomb.writeUInt32LE(oversized, local + 22);
    await expect(inspectZipPackage(bomb)).rejects.toSatisfy(
      expectCode("ZIP_LIMIT_EXCEEDED")
    );

    const misleading = Buffer.from(
      await new JSZip()
        .file("a.txt", "a")
        .file("b.txt", "b")
        .generateAsync({ type: "uint8array", compression: "STORE" })
    );
    const eocd = findSignature(misleading, 0x06054b50);
    expect(eocd).toBeGreaterThanOrEqual(0);
    misleading.writeUInt16LE(1, eocd + 8);
    misleading.writeUInt16LE(1, eocd + 10);
    await expect(inspectZipPackage(misleading)).rejects.toSatisfy(
      expectCode("CORRUPT_OOXML")
    );
  });

  it("keeps source files unchanged when an import is repeated", async () => {
    const sources = await readdir(DATASET);
    const source = resolve(
      DATASET,
      sources.find((name) => name.toLowerCase().endsWith(".xlsx")) ?? ""
    );
    const before = createHash("sha256").update(await readFile(source)).digest("hex");

    await importLegacyWorkbook(source);
    await importLegacyWorkbook(source);

    const after = createHash("sha256").update(await readFile(source)).digest("hex");
    expect(after).toBe(before);
  });

  it("rejects a stale manifest inventory even when its source SHA is pinned", async () => {
    const manifestInput: unknown = JSON.parse(
      await readFile(
        resolve(
          import.meta.dirname,
          "..",
          "..",
          "resources",
          "manifests",
          "legacy",
          "gwangyang-direct-2025.json"
        ),
        "utf8"
      )
    );
    const profile = LegacyProfileManifestSchema.parse(manifestInput);
    let sourceName: string | undefined;
    for (const name of await readdir(DATASET)) {
      const bytes = await readFile(resolve(DATASET, name));
      if (
        createHash("sha256").update(bytes).digest("hex") ===
        profile.source.sha256
      ) {
        sourceName = name;
        break;
      }
    }
    expect(sourceName).toBeDefined();
    if (sourceName === undefined) {
      return;
    }
    const inspected = await inspectZipPackage(
      await readFile(resolve(DATASET, sourceName))
    );
    const ooxml = await inspectOoxmlPackage(inspected);
    const stale = LegacyProfileManifestSchema.parse({
      ...profile,
      baselineInventory: {
        ...profile.baselineInventory,
        externalLinks: {
          ...profile.baselineInventory.externalLinks,
          count: profile.baselineInventory.externalLinks.count + 1
        }
      }
    });

    expect(() => assertProfileMatchesInspection(stale, ooxml)).toThrowError(
      expect.objectContaining({ code: "STALE_PROFILE" })
    );
  });
});
