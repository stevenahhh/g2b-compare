import { createHash } from "node:crypto";
import type JSZip from "jszip";
import { parseWorkbookPackage } from "./workbook.js";
import type {
  BaselineInventory,
  FingerprintCount,
  ResolvedSheet,
  SheetInventory
} from "./ooxml-types.js";
import { parseWorksheetInventory } from "./worksheet-inventory.js";
import { attribute, createXmlParser, zipText } from "./xml.js";
import type { InspectedZipPackage } from "./zip.js";

export type OoxmlInspection = {
  readonly packageParts: FingerprintCount;
  readonly sheetMap: readonly SheetInventory[];
  readonly baselineInventory: BaselineInventory;
  readonly resolvedSheets: readonly ResolvedSheet[];
};

const ERROR_TOKENS = [
  "#REF!",
  "#NAME?",
  "#VALUE!",
  "#DIV/0!",
  "#N/A",
  "#NUM!",
  "#NULL!"
] as const;

export async function inspectOoxmlPackage(
  inspected: InspectedZipPackage
): Promise<OoxmlInspection> {
  const workbook = await parseWorkbookPackage(inspected.archive);
  const sheetMap: SheetInventory[] = [];
  const formulaErrors: string[] = [];
  const cachedErrors: string[] = [];
  for (const sheet of workbook.sheets) {
    const inventory = parseWorksheetInventory(
      sheet,
      await zipText(inspected.archive, sheet.part)
    );
    sheetMap.push(inventory.sheet);
    formulaErrors.push(...inventory.formulaErrors);
    cachedErrors.push(...inventory.cachedErrors);
  }
  const externalLinks = inspected.names.filter(isExternalLinkPart);
  const problemNames = workbook.definedNames.filter(hasErrorToken);
  const externalNames = workbook.definedNames.filter(hasExternalReference);
  const calcChain = await readCalcChain(inspected.archive);
  return {
    packageParts: {
      count: inspected.names.length,
      fingerprint: fingerprint(inspected.names)
    },
    sheetMap,
    baselineInventory: {
      externalLinks: {
        count: externalLinks.length,
        fingerprint: fingerprint(externalLinks)
      },
      definedNames: {
        count: workbook.definedNames.length,
        fingerprint: fingerprint(workbook.definedNames),
        problemCount: problemNames.length,
        problemFingerprint: fingerprint(problemNames),
        externalCount: externalNames.length,
        externalFingerprint: fingerprint(externalNames)
      },
      formulaErrors: {
        formulaTextCount: formulaErrors.length,
        formulaTextFingerprint: fingerprint(formulaErrors),
        cachedErrorCount: cachedErrors.length,
        cachedErrorFingerprint: fingerprint(cachedErrors)
      },
      calcChain: {
        present: calcChain.length > 0,
        entryCount: calcChain.length,
        fingerprint: fingerprint(calcChain)
      }
    },
    resolvedSheets: workbook.sheets
  };
}

async function readCalcChain(archive: JSZip): Promise<readonly string[]> {
  if (archive.files["xl/calcChain.xml"] === undefined) {
    return [];
  }
  const records: string[] = [];
  const parser = createXmlParser();
  parser.on("opentag", (tag) => {
    if (tag.local === "c") {
      records.push([
        attribute(tag, "i") ?? "",
        attribute(tag, "r") ?? "",
        attribute(tag, "l") ?? "",
        attribute(tag, "s") ?? ""
      ].join("|"));
    }
  });
  parser.write(await zipText(archive, "xl/calcChain.xml")).close();
  return records;
}

function fingerprint(records: readonly string[]): string {
  return createHash("sha256").update(records.join("\n")).digest("hex");
}

function hasErrorToken(value: string): boolean {
  return ERROR_TOKENS.some((token) => value.includes(token));
}

function hasExternalReference(value: string): boolean {
  return value.includes("[") && value.includes("]");
}

function isExternalLinkPart(name: string): boolean {
  const prefix = "xl/externalLinks/externalLink";
  const suffix = ".xml";
  const number = name.startsWith(prefix) && name.endsWith(suffix)
    ? name.slice(prefix.length, -suffix.length)
    : "";
  return number.length > 0 && [...number].every(
    (character) => character >= "0" && character <= "9"
  );
}
