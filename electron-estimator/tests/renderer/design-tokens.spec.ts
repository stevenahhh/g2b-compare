import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import path from "node:path";

const STYLE_FILES = [
  "styles.css",
  "workbench-shell.css",
  "workbench-table.css",
  "inspector.css",
  "native-workflow.css",
  "legacy-workflow.css"
] as const;

const OWNED_DECLARATION =
  /^\s*(padding(?:-[\w-]+)?|margin(?:-[\w-]+)?|gap|row-gap|column-gap|font-size|line-height)\s*:\s*([^;]+);/gmu;
const RAW_LENGTH = /(?:^|\s)(?:0|\d+(?:\.\d+)?(?:px|rem|em))(?=\s|$)/u;
const RAW_NONZERO_LENGTH =
  /(?:^|\s)-?(?:(?:\d*[1-9]\d*(?:\.\d+)?)|(?:0?\.\d*[1-9]\d*))(?:px|rem|em)(?=\s|$)/u;

test("spacing and typography declarations use renderer tokens", async () => {
  const violations: string[] = [];

  for (const fileName of STYLE_FILES) {
    const source = await readFile(
      path.resolve(process.cwd(), "src", "renderer", fileName),
      "utf8"
    );
    for (const match of source.matchAll(OWNED_DECLARATION)) {
      const property = match[1];
      const value = match[2];
      const rawLength =
        property?.startsWith("margin") === true
          ? RAW_NONZERO_LENGTH
          : RAW_LENGTH;
      if (
        property !== undefined &&
        value !== undefined &&
        rawLength.test(value)
      ) {
        violations.push(`${fileName}: ${property}: ${value.trim()}`);
      }
    }
  }

  expect(violations).toEqual([]);
});
