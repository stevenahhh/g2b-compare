import { createHash } from "node:crypto";
import {
  cp,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import JSZip from "jszip";
import { createXmlParser } from "../../src/legacy/inspect/xml.js";
import { patchLegacyWorkbook } from "../../src/legacy/patch/index.js";
import {
  calcMetadata,
  sourcesBySha,
  workbookInventory
} from "./ooxml-patch-helpers.js";

const CASES = [
  {
    id: "A",
    sha256: "445012e259ab5318a1d52468cce93ee28a55a8bcb467876f40a47a939e4668db",
    itemCount: 16,
    part: "xl/worksheets/sheet5.xml",
    text: { sheet: "자재내역서", address: "C9" },
    quantity: { sheet: "자재내역서", address: "F9" },
    price: { sheet: "자재내역서", address: "G9" }
  },
  {
    id: "B",
    sha256: "2220cd9936ebdf908d64c0571a4c8de83973eaa89c6778a64afec07de7c5e701",
    itemCount: 9,
    part: "xl/worksheets/sheet13.xml",
    text: { sheet: "수량산출서", address: "B8" },
    quantity: { sheet: "수량산출서", address: "F8" },
    price: { sheet: "단가조사", address: "H5" }
  },
  {
    id: "C",
    sha256: "8a55700bdaf62a00c208c7286531fd56ca321571f73f7620505a823ef5d4d0f1",
    itemCount: 24,
    part: "xl/worksheets/sheet11.xml",
    text: { sheet: "수량산출서", address: "B6" },
    quantity: { sheet: "수량산출서", address: "F6" },
    price: { sheet: "단가조사", address: "H5" }
  }
] as const;

const evidenceArgument = process.argv[2];
if (evidenceArgument === undefined) {
  throw new TypeError("evidence directory argument required");
}
const evidenceDirectory = resolve(evidenceArgument);
const scratch = await mkdtemp(join(tmpdir(), "ooxml-patch-manual-"));
await mkdir(evidenceDirectory, { recursive: true });
const sources = await sourcesBySha();
const records = [];
try {
  for (const fixture of CASES) {
    const source = sources.get(fixture.sha256);
    if (source === undefined) {
      throw new TypeError(`fixture ${fixture.id} missing`);
    }
    const temporarySource = resolve(scratch, `source-${fixture.id}.xlsx`);
    await cp(source, temporarySource);
    const result = await patchLegacyWorkbook({
      source: temporarySource,
      expectedSourceSha256: fixture.sha256,
      itemCount: fixture.itemCount,
      cells: [
        {
          ...fixture.text,
          value: { kind: "text", value: `현장실습 ${fixture.id} <&> =1+1` }
        },
        {
          ...fixture.quantity,
          value: { kind: "number", value: "7.5" }
        },
        {
          ...fixture.price,
          value: { kind: "number", value: "765432" }
        }
      ]
    });
    const output = resolve(evidenceDirectory, `manual-${fixture.id}.xlsx`);
    await writeFile(output, result.workbook);
    const archive = await JSZip.loadAsync(result.workbook);
    const inventory = await workbookInventory(archive);
    const metadata = await calcMetadata(archive);
    records.push({
      profileId: fixture.id,
      sourceSha256: sha256(await readFile(temporarySource)),
      outputSha256: sha256(result.workbook),
      receipt: result.receipt,
      rawTextCell: await rawCell(archive, fixture.part, fixture.text.address),
      formulaFingerprint: sha256(Buffer.from(inventory.formulas.join("\n"))),
      dimensions: inventory.dimensions,
      merges: inventory.merges,
      calcMetadata: {
        calcChainPresent: archive.file("xl/calcChain.xml") !== null,
        relationships: metadata.calcChainRelationships,
        overrides: metadata.calcChainOverrides,
        calcProperties: Object.fromEntries(metadata.calcProperties)
      }
    });
  }
  await writeFile(
    resolve(evidenceDirectory, "task-9-ooxml-patcher.json"),
    `${JSON.stringify(records, null, 2)}\n`,
    "utf8"
  );
} finally {
  await rm(scratch, { recursive: true });
}
await writeFile(
  resolve(evidenceDirectory, "cleanup.json"),
  `${JSON.stringify({ temporaryCopiesRemoved: true })}\n`,
  "utf8"
);
process.stdout.write(`${JSON.stringify({
  profiles: records.length,
  evidenceDirectory,
  temporaryCopiesRemoved: true
})}\n`);

async function rawCell(
  archive: JSZip,
  part: string,
  address: string
): Promise<{
  readonly type: string;
  readonly formula: string;
  readonly value: string;
  readonly text: string;
}> {
  const entry = archive.files[part];
  if (entry === undefined) {
    throw new TypeError(`part ${part} missing`);
  }
  let current = "";
  let type = "";
  let formula = "";
  let value = "";
  let text = "";
  let target = false;
  let content: "formula" | "value" | "text" | null = null;
  const parser = createXmlParser();
  parser.on("opentag", (tag) => {
    if (tag.local === "c") {
      current = tag.attributes["r"]?.value ?? "";
      target = current === address;
      if (target) {
        type = tag.attributes["t"]?.value ?? "";
      }
    } else if (target && tag.local === "f") {
      content = "formula";
    } else if (target && tag.local === "v") {
      content = "value";
    } else if (target && tag.local === "t") {
      content = "text";
    }
  });
  const append = (chunk: string) => {
    if (content === "formula") formula += chunk;
    if (content === "value") value += chunk;
    if (content === "text") text += chunk;
  };
  parser.on("text", append);
  parser.on("cdata", append);
  parser.on("closetag", (tag) => {
    if (tag.local === "f" || tag.local === "v" || tag.local === "t") {
      content = null;
    } else if (tag.local === "c") {
      target = false;
    }
  });
  parser.write(await entry.async("text")).close();
  return { type, formula, value, text };
}

function sha256(value: Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}
