import type JSZip from "jszip";
import {
  SaxesParser,
  type SaxesAttributeNS,
  type SaxesTagNS
} from "saxes";
import { LegacyImportError } from "./errors.js";

const XML_OPTIONS = { xmlns: true } as const;

export function createXmlParser(): SaxesParser<typeof XML_OPTIONS> {
  const parser = new SaxesParser(XML_OPTIONS);
  parser.on("doctype", () => {
    throw new LegacyImportError("CORRUPT_OOXML");
  });
  return parser;
}

export function attribute(
  tag: SaxesTagNS,
  localName: string,
  namespace?: string
): string | undefined {
  return Object.values(tag.attributes).find(
    (item: SaxesAttributeNS) =>
      item.local === localName &&
      (namespace === undefined || item.uri === namespace)
  )?.value;
}

export async function zipText(archive: JSZip, part: string): Promise<string> {
  const entry = archive.files[part];
  if (entry === undefined || entry.dir) {
    throw new LegacyImportError("CORRUPT_OOXML");
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(
      await entry.async("uint8array")
    );
  } catch (error) {
    if (error instanceof LegacyImportError) {
      throw error;
    }
    throw new LegacyImportError("CORRUPT_OOXML");
  }
}
