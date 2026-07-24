import type JSZip from "jszip";
import Decimal from "decimal.js";
import { LegacyImportError } from "./errors.js";
import type {
  LegacyCellValue,
  LegacyScalarValue
} from "./types.js";
import { attribute, createXmlParser, zipText } from "./xml.js";

type MutableCell = {
  readonly address: string;
  readonly type: string;
  formula: string | undefined;
  cached: string;
  inline: string;
  inFormula: boolean;
  inValue: boolean;
  inInline: boolean;
};

type WorksheetCellContext = {
  readonly wanted: ReadonlySet<string>;
  readonly sharedStrings: readonly string[];
  readonly xml: string;
};

export function parseWorksheetCells(
  context: WorksheetCellContext
): ReadonlyMap<string, LegacyCellValue> {
  const values = new Map<string, LegacyCellValue>();
  let current: MutableCell | undefined;
  const parser = createXmlParser();
  parser.on("opentag", (tag) => {
    if (tag.local === "c") {
      const address = attribute(tag, "r") ?? "";
      current = context.wanted.has(address)
        ? {
            address,
            type: attribute(tag, "t") ?? "",
            formula: undefined,
            cached: "",
            inline: "",
            inFormula: false,
            inValue: false,
            inInline: false
          }
        : undefined;
    } else if (current !== undefined && tag.local === "f") {
      current.formula = "";
      current.inFormula = true;
    } else if (current !== undefined && tag.local === "v") {
      current.inValue = true;
    } else if (current !== undefined && tag.local === "t") {
      current.inInline = true;
    }
  });
  const append = (text: string) => {
    if (current?.inFormula === true && current.formula !== undefined) {
      current.formula += text;
    } else if (current?.inValue === true) {
      current.cached += text;
    } else if (current?.inInline === true) {
      current.inline += text;
    }
  };
  parser.on("text", append);
  parser.on("cdata", append);
  parser.on("closetag", (tag) => {
    if (current === undefined) {
      return;
    }
    if (tag.local === "f") {
      current.inFormula = false;
    } else if (tag.local === "v") {
      current.inValue = false;
    } else if (tag.local === "t") {
      current.inInline = false;
    } else if (tag.local === "c") {
      const cached = scalarValue(current, context.sharedStrings);
      values.set(
        current.address,
        current.formula === undefined
          ? cached
          : {
              kind: "formula",
              untrustedFormula: current.formula,
              cached
            }
      );
      current = undefined;
    }
  });
  parser.write(context.xml).close();
  return values;
}

function scalarValue(
  cell: MutableCell,
  sharedStrings: readonly string[]
): LegacyScalarValue {
  switch (cell.type) {
    case "inlineStr":
      return { kind: "text", value: cell.inline };
    case "s": {
      const index = Number(cell.cached);
      const value = Number.isInteger(index) ? sharedStrings[index] : undefined;
      if (value === undefined) {
        throw new LegacyImportError("CORRUPT_OOXML");
      }
      return { kind: "text", value };
    }
    case "str":
      return { kind: "text", value: cell.cached };
    case "b":
      if (cell.cached !== "0" && cell.cached !== "1") {
        throw new LegacyImportError("CORRUPT_OOXML");
      }
      return { kind: "boolean", value: cell.cached === "1" };
    case "e":
      return { kind: "error", value: cell.cached };
    case "":
    case "n":
      if (cell.cached === "") {
        return { kind: "blank" };
      }
      new Decimal(cell.cached);
      return { kind: "number", value: cell.cached };
    default:
      throw new LegacyImportError("CORRUPT_OOXML");
  }
}

export async function readSharedStrings(
  archive: JSZip
): Promise<readonly string[]> {
  if (archive.files["xl/sharedStrings.xml"] === undefined) {
    return [];
  }
  const strings: string[] = [];
  let current: string | undefined;
  let inText = false;
  const parser = createXmlParser();
  parser.on("opentag", (tag) => {
    if (tag.local === "si") {
      current = "";
    } else if (tag.local === "t" && current !== undefined) {
      inText = true;
    }
  });
  const append = (text: string) => {
    if (inText && current !== undefined) {
      current += text;
    }
  };
  parser.on("text", append);
  parser.on("cdata", append);
  parser.on("closetag", (tag) => {
    if (tag.local === "t") {
      inText = false;
    } else if (tag.local === "si" && current !== undefined) {
      strings.push(current);
      current = undefined;
    }
  });
  parser.write(await zipText(archive, "xl/sharedStrings.xml")).close();
  return strings;
}
