import { posix } from "node:path";
import type JSZip from "jszip";
import { LegacyImportError } from "./errors.js";
import type { ResolvedSheet } from "./ooxml-types.js";
import { attribute, createXmlParser, zipText } from "./xml.js";

const RELATIONSHIP_NAMESPACE =
  "http://schemas.openxmlformats.org/officeDocument/2006/relationships";

export async function parseWorkbookPackage(archive: JSZip): Promise<{
  readonly sheets: readonly ResolvedSheet[];
  readonly definedNames: readonly string[];
}> {
  const relationships = parseRelationships(
    await zipText(archive, "xl/_rels/workbook.xml.rels")
  );
  const xml = await zipText(archive, "xl/workbook.xml");
  const sheets: ResolvedSheet[] = [];
  const definedNames: string[] = [];
  let currentDefinedName:
    | { readonly prefix: string; text: string }
    | undefined;
  const parser = createXmlParser();
  parser.on("opentag", (tag) => {
    if (tag.local === "sheet") {
      const name = attribute(tag, "name");
      const relationshipId = attribute(tag, "id", RELATIONSHIP_NAMESPACE);
      const target = relationshipId === undefined
        ? undefined
        : relationships.get(relationshipId);
      if (name === undefined || target === undefined) {
        throw new LegacyImportError("CORRUPT_OOXML");
      }
      sheets.push({ name, part: resolveWorkbookPart(target) });
    }
    if (tag.local === "definedName") {
      currentDefinedName = {
        prefix: [
          attribute(tag, "name") ?? "",
          attribute(tag, "localSheetId") ?? "",
          attribute(tag, "hidden") ?? ""
        ].join("|"),
        text: ""
      };
    }
  });
  const appendDefinedName = (text: string) => {
    if (currentDefinedName !== undefined) {
      currentDefinedName.text += text;
    }
  };
  parser.on("text", appendDefinedName);
  parser.on("cdata", appendDefinedName);
  parser.on("closetag", (tag) => {
    if (tag.local === "definedName" && currentDefinedName !== undefined) {
      definedNames.push(`${currentDefinedName.prefix}|${currentDefinedName.text}`);
      currentDefinedName = undefined;
    }
  });
  parser.write(xml).close();
  return { sheets, definedNames };
}

function parseRelationships(xml: string): ReadonlyMap<string, string> {
  const relationships = new Map<string, string>();
  const parser = createXmlParser();
  parser.on("opentag", (tag) => {
    if (tag.local !== "Relationship") {
      return;
    }
    const id = attribute(tag, "Id");
    const target = attribute(tag, "Target");
    const targetMode = attribute(tag, "TargetMode");
    if (id !== undefined && target !== undefined && targetMode !== "External") {
      relationships.set(id, target);
    }
  });
  parser.write(xml).close();
  return relationships;
}

function resolveWorkbookPart(target: string): string {
  const segments = target.split("/");
  if (segments.some((segment) => segment === ".." || segment === ".")) {
    throw new LegacyImportError("CORRUPT_OOXML");
  }
  const part = target.startsWith("/")
    ? target.slice(1)
    : posix.join("xl", target);
  if (!part.startsWith("xl/")) {
    throw new LegacyImportError("CORRUPT_OOXML");
  }
  return part;
}
