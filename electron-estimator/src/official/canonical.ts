import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import type { z } from "zod";
import { OfficialDataError } from "./errors.js";

export function canonicalJson(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  switch (typeof value) {
    case "boolean":
    case "number":
    case "string":
      return JSON.stringify(value);
    case "object":
      return `{${Object.entries(value)
        .sort(([left], [right]) =>
          left < right ? -1 : left > right ? 1 : 0
        )
        .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
        .join(",")}}`;
    default:
      throw new OfficialDataError(
        "OFFICIAL_DATA_MALFORMED_JSON",
        "unsupported JSON value"
      );
  }
}

export function sha256(value: string | Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

export function assertSafeText(value: unknown, path = "$"): void {
  if (typeof value === "string") {
    const hasControl = [...value].some(
      (character) => (character.codePointAt(0) ?? 0) < 32
    );
    if (hasControl || /^\s*[=+\-@]/u.test(value)) {
      throw new OfficialDataError(
        "OFFICIAL_DATA_UNSAFE_TEXT",
        `unsafe text at ${path}`
      );
    }
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => {
      assertSafeText(item, `${path}[${index}]`);
    });
    return;
  }
  if (value !== null && typeof value === "object") {
    Object.entries(value).forEach(([key, item]) => {
      assertSafeText(item, `${path}.${key}`);
    });
  }
}

export async function readCanonicalJson<T>(
  path: string,
  schema: z.ZodType<T>
): Promise<{ readonly parsed: T; readonly raw: Readonly<Record<string, unknown>> }> {
  const text = await readFile(path, "utf8");
  if (text.startsWith("\uFEFF") || text.includes("\r")) {
    throw new OfficialDataError(
      "OFFICIAL_DATA_NON_CANONICAL_JSON",
      `${path} must be UTF-8 without BOM or CR`
    );
  }
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new OfficialDataError(
      "OFFICIAL_DATA_MALFORMED_JSON",
      `malformed JSON in ${path}`
    );
  }
  assertSafeText(value);
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new OfficialDataError(
      "OFFICIAL_DATA_MALFORMED_JSON",
      `${path} must contain an object`
    );
  }
  const raw = Object.freeze(Object.fromEntries(Object.entries(value)));
  try {
    return { parsed: schema.parse(value), raw };
  } catch {
    throw new OfficialDataError(
      "OFFICIAL_DATA_ROW_SCHEMA",
      `schema mismatch in ${path}`
    );
  }
}

export async function readCanonicalJsonl<T>(
  path: string,
  schema: z.ZodType<T>
): Promise<{
  readonly bytes: Uint8Array;
  readonly rows: readonly T[];
}> {
  const bytes = await readFile(path);
  const text = bytes.toString("utf8");
  if (text.startsWith("\uFEFF") || text.includes("\r")) {
    throw new OfficialDataError(
      "OFFICIAL_DATA_NON_CANONICAL_JSON",
      `${path} must be UTF-8 LF without BOM`
    );
  }
  if (!text.endsWith("\n")) {
    throw new OfficialDataError(
      "OFFICIAL_DATA_INTERRUPTED_GENERATION",
      `${path} has no final LF`
    );
  }
  const rows = text
    .slice(0, -1)
    .split("\n")
    .map((line, index) => {
      let value: unknown;
      try {
        value = JSON.parse(line);
      } catch {
        throw new OfficialDataError(
          "OFFICIAL_DATA_MALFORMED_JSON",
          `malformed JSON at ${path}:${index + 1}`
        );
      }
      assertSafeText(value, `$[${index}]`);
      if (canonicalJson(value) !== line) {
        throw new OfficialDataError(
          "OFFICIAL_DATA_NON_CANONICAL_JSON",
          `non-canonical row at ${path}:${index + 1}`
        );
      }
      try {
        return schema.parse(value);
      } catch {
        throw new OfficialDataError(
          "OFFICIAL_DATA_ROW_SCHEMA",
          `schema mismatch at ${path}:${index + 1}`
        );
      }
    });
  return { bytes, rows: Object.freeze(rows) };
}

export async function readCanonicalJsonArray<T>(
  path: string,
  schema: z.ZodType<T>
): Promise<{
  readonly bytes: Uint8Array;
  readonly rows: readonly T[];
}> {
  const bytes = await readFile(path);
  const text = bytes.toString("utf8");
  if (text.startsWith("\uFEFF") || text.includes("\r") || !text.endsWith("\n")) {
    throw new OfficialDataError(
      "OFFICIAL_DATA_INTERRUPTED_GENERATION",
      `${path} must be canonical UTF-8 LF`
    );
  }
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new OfficialDataError(
      "OFFICIAL_DATA_MALFORMED_JSON",
      `malformed JSON in ${path}`
    );
  }
  assertSafeText(value);
  if (!Array.isArray(value) || `${canonicalJson(value)}\n` !== text) {
    throw new OfficialDataError(
      "OFFICIAL_DATA_NON_CANONICAL_JSON",
      `${path} must contain a canonical JSON array`
    );
  }
  const rows = value.map((row, index) => {
    try {
      return schema.parse(row);
    } catch {
      throw new OfficialDataError(
        "SOURCED_PRODUCTS_ROW_SCHEMA",
        `schema mismatch at ${path}:${index + 1}`
      );
    }
  });
  return { bytes, rows: Object.freeze(rows) };
}
