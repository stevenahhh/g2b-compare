import { LegacyImportError } from "./errors.js";
import type {
  ResolvedSheet,
  SheetInventory
} from "./ooxml-types.js";
import { attribute, createXmlParser } from "./xml.js";

const ERROR_TOKENS = [
  "#REF!",
  "#NAME?",
  "#VALUE!",
  "#DIV/0!",
  "#N/A",
  "#NUM!",
  "#NULL!"
] as const;

export function parseWorksheetInventory(
  sheet: ResolvedSheet,
  xml: string
): {
  readonly sheet: SheetInventory;
  readonly formulaErrors: readonly string[];
  readonly cachedErrors: readonly string[];
} {
  const formulaErrors: string[] = [];
  const cachedErrors: string[] = [];
  let dimension: string | undefined;
  let formulaCells = 0;
  let mergedRanges = 0;
  let cellAddress = "";
  let cellType = "";
  let formula: string | undefined;
  let cached = "";
  let inFormula = false;
  let inValue = false;
  let externalFormulaReferences = 0;
  const parser = createXmlParser();
  parser.on("opentag", (tag) => {
    if (tag.local === "dimension") {
      dimension = attribute(tag, "ref");
    } else if (tag.local === "mergeCell") {
      mergedRanges += 1;
    } else if (tag.local === "c") {
      cellAddress = attribute(tag, "r") ?? "";
      cellType = attribute(tag, "t") ?? "";
      formula = undefined;
      cached = "";
    } else if (tag.local === "f") {
      formulaCells += 1;
      formula = "";
      inFormula = true;
    } else if (tag.local === "v") {
      inValue = true;
    }
  });
  const append = (text: string) => {
    if (inFormula && formula !== undefined) {
      formula += text;
    } else if (inValue) {
      cached += text;
    }
  };
  parser.on("text", append);
  parser.on("cdata", append);
  parser.on("closetag", (tag) => {
    if (tag.local === "f") {
      inFormula = false;
    } else if (tag.local === "v") {
      inValue = false;
    } else if (tag.local === "c") {
      if (formula !== undefined) {
        if (formula.includes("[") && formula.includes("]")) {
          externalFormulaReferences += 1;
        }
        if (ERROR_TOKENS.some((token) => formula?.includes(token))) {
          formulaErrors.push(`${sheet.name}!${cellAddress}=${formula}`);
        }
      }
      if (cellType === "e") {
        cachedErrors.push(`${sheet.name}!${cellAddress}=${cached}`);
      }
    }
  });
  parser.write(xml).close();
  if (dimension === undefined) {
    throw new LegacyImportError("CORRUPT_OOXML");
  }
  return {
    sheet: {
      ...sheet,
      dimension,
      formulaCells,
      mergedRanges,
      externalFormulaReferences
    },
    formulaErrors,
    cachedErrors
  };
}
