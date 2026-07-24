import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";
import type JSZip from "jszip";
import { createXmlParser } from "../../src/legacy/inspect/xml.js";

export const DATASET = resolve(
  import.meta.dirname,
  "..",
  "..",
  "..",
  "dataset"
);

export async function sourcesBySha(): Promise<ReadonlyMap<string, string>> {
  const sources = new Map<string, string>();
  for (const filename of await readdir(DATASET)) {
    if (filename.toLowerCase().endsWith(".xlsx") && !filename.startsWith("~$")) {
      const path = resolve(DATASET, filename);
      const bytes = await readFile(path);
      sources.set(createHash("sha256").update(bytes).digest("hex"), path);
    }
  }
  return sources;
}

export async function workbookInventory(archive: JSZip) {
  const dimensions: string[] = [];
  const formulas: string[] = [];
  const merges: string[] = [];
  const formulaCaches = new Set<string>();
  const styles = new Map<string, string>();
  for (const part of Object.keys(archive.files).toSorted()) {
    const entry = archive.files[part];
    if (
      entry === undefined ||
      entry.dir ||
      !part.startsWith("xl/worksheets/")
    ) {
      continue;
    }
    let cell = "";
    let formula = "";
    let hasFormula = false;
    let hasValue = false;
    let inFormula = false;
    const parser = createXmlParser();
    parser.on("opentag", (tag) => {
      if (tag.local === "dimension") {
        dimensions.push(`${part}:${tag.attributes["ref"]?.value ?? ""}`);
      } else if (tag.local === "mergeCell") {
        merges.push(`${part}:${tag.attributes["ref"]?.value ?? ""}`);
      } else if (tag.local === "c") {
        cell = tag.attributes["r"]?.value ?? "";
        hasFormula = false;
        hasValue = false;
        styles.set(`${part}!${cell}`, tag.attributes["s"]?.value ?? "");
      } else if (tag.local === "f") {
        formula = "";
        hasFormula = true;
        inFormula = true;
      } else if (tag.local === "v") {
        hasValue = true;
      }
    });
    const append = (text: string) => {
      if (inFormula) {
        formula += text;
      }
    };
    parser.on("text", append);
    parser.on("cdata", append);
    parser.on("closetag", (tag) => {
      if (tag.local === "f") {
        formulas.push(`${part}!${cell}=${formula}`);
        inFormula = false;
      } else if (tag.local === "c" && hasFormula && hasValue) {
        formulaCaches.add(`${part}!${cell}`);
      }
    });
    parser.write(await entry.async("text")).close();
  }
  return { dimensions, formulas, merges, formulaCaches, styles };
}

export async function packageHashes(
  archive: JSZip
): Promise<ReadonlyMap<string, string>> {
  const hashes = new Map<string, string>();
  for (const name of Object.keys(archive.files).toSorted()) {
    const entry = archive.files[name];
    if (entry !== undefined && !entry.dir) {
      hashes.set(
        name,
        createHash("sha256")
          .update(await entry.async("uint8array"))
          .digest("hex")
      );
    }
  }
  return hashes;
}

export function changedPackageParts(
  before: ReadonlyMap<string, string>,
  after: ReadonlyMap<string, string>
): readonly string[] {
  const names = new Set([...before.keys(), ...after.keys()]);
  return [...names]
    .filter((name) => before.get(name) !== after.get(name))
    .toSorted();
}

export async function calcMetadata(archive: JSZip) {
  let calcChainRelationships = 0;
  let calcChainOverrides = 0;
  const calcProperties = new Map<string, string>();
  for (const [part, local] of [
    ["xl/_rels/workbook.xml.rels", "Relationship"],
    ["[Content_Types].xml", "Override"],
    ["xl/workbook.xml", "calcPr"]
  ] as const) {
    const entry = archive.files[part];
    if (entry === undefined) {
      continue;
    }
    const parser = createXmlParser();
    parser.on("opentag", (tag) => {
      if (
        local === "Relationship" &&
        tag.local === local &&
        tag.attributes["Type"]?.value.endsWith("/calcChain") === true
      ) {
        calcChainRelationships += 1;
      } else if (
        local === "Override" &&
        tag.local === local &&
        tag.attributes["PartName"]?.value === "/xl/calcChain.xml"
      ) {
        calcChainOverrides += 1;
      } else if (local === "calcPr" && tag.local === local) {
        Object.values(tag.attributes).forEach((attribute) => {
          calcProperties.set(attribute.local, attribute.value);
        });
      }
    });
    parser.write(await entry.async("text")).close();
  }
  return { calcChainRelationships, calcChainOverrides, calcProperties };
}

