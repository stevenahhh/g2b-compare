import type { SaxesAttributeNS } from "saxes";
import { LegacyImportError } from "../inspect/errors.js";
import { createXmlParser } from "../inspect/xml.js";

export type XmlAttribute = {
  readonly name: string;
  readonly local: string;
  readonly value: string;
};

export type ScannedXmlNode = {
  readonly name: string;
  readonly local: string;
  readonly attributes: readonly XmlAttribute[];
  readonly start: number;
  readonly openEnd: number;
  closeStart: number;
  end: number;
  readonly selfClosing: boolean;
  readonly parent: ScannedXmlNode | null;
};

export type XmlReplacement = {
  readonly start: number;
  readonly end: number;
  readonly value: string;
};

export function scanXmlNodes(xml: string): readonly ScannedXmlNode[] {
  const nodes: ScannedXmlNode[] = [];
  const stack: ScannedXmlNode[] = [];
  const parser = createXmlParser();
  parser.on("opentag", (tag) => {
    const openEnd = parser.position;
    const start = xml.lastIndexOf("<", openEnd - 1);
    if (start < 0) {
      throw new LegacyImportError("CORRUPT_OOXML");
    }
    const node: ScannedXmlNode = {
      name: tag.name,
      local: tag.local,
      attributes: Object.values(tag.attributes).map(
        (attribute: SaxesAttributeNS) => ({
          name: attribute.name,
          local: attribute.local,
          value: attribute.value
        })
      ),
      start,
      openEnd,
      closeStart: openEnd,
      end: openEnd,
      selfClosing: tag.isSelfClosing,
      parent: stack.at(-1) ?? null
    };
    nodes.push(node);
    if (!tag.isSelfClosing) {
      stack.push(node);
    }
  });
  parser.on("closetag", (tag) => {
    if (tag.isSelfClosing) {
      return;
    }
    const node = stack.pop();
    const closeStart = xml.lastIndexOf("<", parser.position - 1);
    if (
      node === undefined ||
      node.local !== tag.local ||
      closeStart < node.openEnd
    ) {
      throw new LegacyImportError("CORRUPT_OOXML");
    }
    node.closeStart = closeStart;
    node.end = parser.position;
  });
  parser.write(xml).close();
  if (stack.length !== 0) {
    throw new LegacyImportError("CORRUPT_OOXML");
  }
  return nodes;
}

export function applyXmlReplacements(
  xml: string,
  replacements: readonly XmlReplacement[]
): string {
  let result = xml;
  let boundary = xml.length;
  for (const replacement of replacements.toSorted(
    (left, right) => right.start - left.start
  )) {
    if (
      replacement.start < 0 ||
      replacement.end < replacement.start ||
      replacement.end > boundary
    ) {
      throw new LegacyImportError("CORRUPT_OOXML");
    }
    result = result.slice(0, replacement.start) +
      replacement.value +
      result.slice(replacement.end);
    boundary = replacement.start;
  }
  return result;
}

export function rewriteNodeTag(
  node: ScannedXmlNode,
  overrides: ReadonlyMap<string, string | undefined>,
  selfClosing = node.selfClosing
): string {
  const attributes: string[] = [];
  const seen = new Set<string>();
  for (const attribute of node.attributes) {
    seen.add(attribute.local);
    if (overrides.has(attribute.local)) {
      const value = overrides.get(attribute.local);
      if (value !== undefined) {
        attributes.push(`${attribute.name}="${escapeAttribute(value)}"`);
      }
    } else {
      attributes.push(
        `${attribute.name}="${escapeAttribute(attribute.value)}"`
      );
    }
  }
  for (const [name, value] of overrides) {
    if (!seen.has(name) && value !== undefined) {
      attributes.push(`${name}="${escapeAttribute(value)}"`);
    }
  }
  const suffix = selfClosing ? "/>" : ">";
  return `<${node.name}${attributes.length > 0 ? ` ${attributes.join(" ")}` : ""}${suffix}`;
}

export function nodeAttribute(
  node: ScannedXmlNode,
  local: string
): string | undefined {
  return node.attributes.find((attribute) => attribute.local === local)?.value;
}

function escapeAttribute(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

