import { parseAddress } from "../inspect/cell-address.js";
import { LegacyImportError } from "../inspect/errors.js";
import type { LegacyScalarValue } from "../inspect/types.js";
import type { PatchCellValue } from "./types.js";
import {
  applyXmlReplacements,
  nodeAttribute,
  rewriteNodeTag,
  scanXmlNodes,
  type ScannedXmlNode,
  type XmlReplacement
} from "./xml-nodes.js";

type WorksheetWrite = {
  readonly address: string;
  readonly value: PatchCellValue;
};

type WorksheetPatchInput = {
  readonly xml: string;
  readonly writes: readonly WorksheetWrite[];
  readonly cacheAddresses: ReadonlySet<string>;
  readonly date1904: boolean;
};

export function patchWorksheetXml(input: WorksheetPatchInput): {
  readonly xml: string;
  readonly affectedCaches: readonly string[];
} {
  const nodes = scanXmlNodes(input.xml);
  const cells = new Map(
    nodes
      .filter((node) => node.local === "c")
      .map((node) => [nodeAttribute(node, "r") ?? "", node])
  );
  const writeAddresses = new Set(input.writes.map((write) => write.address));
  const replacements: XmlReplacement[] = [];
  for (const write of input.writes) {
    const cell = cells.get(write.address);
    if (cell === undefined || cell.selfClosing) {
      throw new LegacyImportError("STALE_PROFILE");
    }
    replacements.push({
      start: cell.start,
      end: cell.end,
      value: serializeCell({
        xml: input.xml,
        nodes,
        cell,
        value: write.value,
        date1904: input.date1904
      })
    });
  }
  const affectedCaches: string[] = [];
  for (const address of input.cacheAddresses) {
    if (writeAddresses.has(address)) {
      continue;
    }
    const cell = cells.get(address);
    if (cell === undefined || directChild(nodes, cell, "f") === undefined) {
      continue;
    }
    const cached = directChild(nodes, cell, "v");
    if (cached !== undefined) {
      replacements.push({
        start: cached.start,
        end: cached.end,
        value: ""
      });
      affectedCaches.push(address);
    }
  }
  return {
    xml: applyXmlReplacements(input.xml, replacements),
    affectedCaches: affectedCaches.toSorted(compareAddresses)
  };
}

export function workbookUsesDate1904(xml: string): boolean {
  const workbookProperties = scanXmlNodes(xml).find(
    (node) => node.local === "workbookPr"
  );
  const value = workbookProperties === undefined
    ? undefined
    : nodeAttribute(workbookProperties, "date1904");
  return value === "1" || value === "true";
}

export function comparableValue(
  value: PatchCellValue,
  date1904: boolean
): LegacyScalarValue {
  switch (value.kind) {
    case "blank":
      return value;
    case "text":
    case "number":
      return value;
    case "date":
      return {
        kind: "number",
        value: excelDateSerial(value.value, date1904)
      };
    default:
      return assertNever(value);
  }
}

function directChild(
  nodes: readonly ScannedXmlNode[],
  parent: ScannedXmlNode,
  local: string
): ScannedXmlNode | undefined {
  return nodes.find((node) => node.parent === parent && node.local === local);
}

type CellSerializationInput = {
  readonly xml: string;
  readonly nodes: readonly ScannedXmlNode[];
  readonly cell: ScannedXmlNode;
  readonly value: PatchCellValue;
  readonly date1904: boolean;
};

function serializeCell(input: CellSerializationInput): string {
  const overrides = new Map<string, string | undefined>();
  overrides.set(
    "t",
    input.value.kind === "text" ? "inlineStr" : undefined
  );
  const open = rewriteNodeTag(input.cell, overrides, false);
  const preserved = input.nodes
    .filter(
      (node) =>
        node.parent === input.cell &&
        node.local !== "f" &&
        node.local !== "v" &&
        node.local !== "is"
    )
    .map((node) => input.xml.slice(node.start, node.end))
    .join("");
  switch (input.value.kind) {
    case "blank":
      return `${open}${preserved}</${input.cell.name}>`;
    case "number":
      return `${open}<v>${input.value.value}</v>${preserved}</${input.cell.name}>`;
    case "date":
      return `${open}<v>${excelDateSerial(input.value.value, input.date1904)}</v>${preserved}</${input.cell.name}>`;
    case "text": {
      const preserve = input.value.value.trim() === input.value.value
        ? ""
        : ' xml:space="preserve"';
      return `${open}<is><t${preserve}>${escapeText(input.value.value)}</t></is>${preserved}</${input.cell.name}>`;
    }
    default:
      return assertNever(input.value);
  }
}

function excelDateSerial(value: string, date1904: boolean): string {
  const [yearText, monthText, dayText] = value.split("-");
  const timestamp = Date.UTC(
    Number(yearText),
    Number(monthText) - 1,
    Number(dayText)
  );
  const dayMilliseconds = 86_400_000;
  if (date1904) {
    return String((timestamp - Date.UTC(1904, 0, 1)) / dayMilliseconds);
  }
  const base = (timestamp - Date.UTC(1899, 11, 31)) / dayMilliseconds;
  return String(timestamp >= Date.UTC(1900, 2, 1) ? base + 1 : base);
}

function escapeText(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function compareAddresses(left: string, right: string): number {
  const leftPoint = parseAddress(left);
  const rightPoint = parseAddress(right);
  return leftPoint.row - rightPoint.row ||
    leftPoint.column - rightPoint.column;
}

function assertNever(value: never): never {
  throw new LegacyImportError("CORRUPT_OOXML");
}
