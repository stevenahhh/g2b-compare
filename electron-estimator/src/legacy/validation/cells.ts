import type JSZip from "jszip";
import type { SaxesAttributeNS } from "saxes";
import { parseAddress } from "../inspect/cell-address.js";
import type { ResolvedSheet } from "../inspect/ooxml-types.js";
import {
  attribute,
  createXmlParser,
  zipText
} from "../inspect/xml.js";
import { canonicalJson, sha256 } from "./canonical.js";
import type { PatchCellReference } from "./types.js";

type SemanticValue =
  | { readonly kind: "blank" }
  | { readonly kind: "text"; readonly value: string }
  | { readonly kind: "number"; readonly value: string }
  | { readonly kind: "boolean"; readonly value: string }
  | { readonly kind: "error"; readonly value: string };

type SemanticCell = {
  readonly formula: string | null;
  readonly value: SemanticValue;
};

export type SemanticCellChange = PatchCellReference & {
  readonly beforeSha256: string;
  readonly outputSha256: string;
  readonly formulaChanged: boolean;
  readonly cacheChanged: boolean;
};

export async function diffSemanticCells(
  originalArchive: JSZip,
  outputArchive: JSZip,
  originalSheets: readonly ResolvedSheet[],
  outputSheets: readonly ResolvedSheet[]
): Promise<readonly SemanticCellChange[]> {
  const originalStrings = await readSharedStrings(originalArchive);
  const outputStrings = await readSharedStrings(outputArchive);
  const outputByName = new Map(
    outputSheets.map((sheet) => [sheet.name, sheet])
  );
  const changes: SemanticCellChange[] = [];
  for (const sheet of originalSheets) {
    const outputSheet = outputByName.get(sheet.name);
    if (outputSheet === undefined) {
      continue;
    }
    const original = parseCells(
      await zipText(originalArchive, sheet.part),
      originalStrings
    );
    const output = parseCells(
      await zipText(outputArchive, outputSheet.part),
      outputStrings
    );
    const addresses = new Set([...original.keys(), ...output.keys()]);
    for (const address of addresses) {
      const before = original.get(address);
      const after = output.get(address);
      const beforeJson = canonicalJson(before ?? null);
      const afterJson = canonicalJson(after ?? null);
      if (beforeJson === afterJson) {
        continue;
      }
      changes.push({
        sheet: sheet.name,
        address,
        beforeSha256: sha256(beforeJson),
        outputSha256: sha256(afterJson),
        formulaChanged: before?.formula !== after?.formula,
        cacheChanged:
          before?.formula !== null &&
          before?.formula === after?.formula &&
          canonicalJson(before?.value) !== canonicalJson(after?.value)
      });
    }
  }
  const sheetOrder = originalSheets.map(({ name }) => name);
  return changes.toSorted((left, right) =>
    compareReferences(left, right, sheetOrder)
  );
}

export function compareReferences(
  left: PatchCellReference,
  right: PatchCellReference,
  sheetOrder: readonly string[]
): number {
  const leftAddress = parseAddress(left.address);
  const rightAddress = parseAddress(right.address);
  return (
    sheetOrder.indexOf(left.sheet) - sheetOrder.indexOf(right.sheet) ||
    leftAddress.row - rightAddress.row ||
    leftAddress.column - rightAddress.column
  );
}

function parseCells(
  xml: string,
  sharedStrings: readonly string[]
): ReadonlyMap<string, SemanticCell> {
  const cells = new Map<string, SemanticCell>();
  let address = "";
  let cellType = "";
  let rawValue = "";
  let inlineText = "";
  let formulaText: string | undefined;
  let formulaAttributes = "";
  let inFormula = false;
  let inValue = false;
  let inInlineText = false;
  const parser = createXmlParser();
  parser.on("opentag", (tag) => {
    switch (tag.local) {
      case "c":
        address = attribute(tag, "r") ?? "";
        cellType = attribute(tag, "t") ?? "";
        rawValue = "";
        inlineText = "";
        formulaText = undefined;
        formulaAttributes = "";
        break;
      case "f":
        formulaText = "";
        formulaAttributes = Object.values(tag.attributes)
          .map(
            (item: SaxesAttributeNS) =>
              `${item.uri}|${item.local}|${item.value}`
          )
          .toSorted()
          .join("\n");
        inFormula = true;
        break;
      case "v":
        inValue = true;
        break;
      case "t":
        inInlineText = cellType === "inlineStr";
        break;
      default:
        break;
    }
  });
  const append = (text: string) => {
    if (inFormula && formulaText !== undefined) {
      formulaText += text;
    } else if (inValue) {
      rawValue += text;
    } else if (inInlineText) {
      inlineText += text;
    }
  };
  parser.on("text", append);
  parser.on("cdata", append);
  parser.on("closetag", (tag) => {
    switch (tag.local) {
      case "f":
        inFormula = false;
        break;
      case "v":
        inValue = false;
        break;
      case "t":
        inInlineText = false;
        break;
      case "c": {
        const value = semanticValue(
          cellType,
          rawValue,
          inlineText,
          sharedStrings
        );
        const formula =
          formulaText === undefined
            ? null
            : `${formulaAttributes}\u0000${formulaText}`;
        if (formula !== null || value.kind !== "blank") {
          cells.set(address, { formula, value });
        }
        break;
      }
      default:
        break;
    }
  });
  parser.write(xml).close();
  return cells;
}

function semanticValue(
  cellType: string,
  rawValue: string,
  inlineText: string,
  sharedStrings: readonly string[]
): SemanticValue {
  if (cellType === "inlineStr") {
    return inlineText.length === 0
      ? { kind: "blank" }
      : { kind: "text", value: inlineText };
  }
  if (rawValue.length === 0) {
    return { kind: "blank" };
  }
  if (cellType === "s") {
    const value = sharedStrings[Number(rawValue)];
    if (value === undefined) {
      throw new TypeError("INVALID_SHARED_STRING");
    }
    return { kind: "text", value };
  }
  if (cellType === "str") {
    return { kind: "text", value: rawValue };
  }
  if (cellType === "b") {
    return { kind: "boolean", value: rawValue };
  }
  if (cellType === "e") {
    return { kind: "error", value: rawValue };
  }
  return { kind: "number", value: rawValue };
}

async function readSharedStrings(archive: JSZip): Promise<readonly string[]> {
  if (archive.files["xl/sharedStrings.xml"] === undefined) {
    return [];
  }
  const strings: string[] = [];
  let text = "";
  let inItem = false;
  let inText = false;
  const parser = createXmlParser();
  parser.on("opentag", (tag) => {
    if (tag.local === "si") {
      text = "";
      inItem = true;
    } else if (tag.local === "t" && inItem) {
      inText = true;
    }
  });
  const append = (value: string) => {
    if (inText) {
      text += value;
    }
  };
  parser.on("text", append);
  parser.on("cdata", append);
  parser.on("closetag", (tag) => {
    if (tag.local === "t") {
      inText = false;
    } else if (tag.local === "si") {
      strings.push(text);
      inItem = false;
    }
  });
  parser.write(await zipText(archive, "xl/sharedStrings.xml")).close();
  return strings;
}
