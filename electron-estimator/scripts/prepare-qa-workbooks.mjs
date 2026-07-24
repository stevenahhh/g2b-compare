import { build } from "esbuild";
import { createHash } from "node:crypto";
import {
  mkdir,
  readFile,
  rm,
  writeFile
} from "node:fs/promises";
import { basename, dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { verifyWorkbook } from "./verify-workbook.mjs";

const PROJECT_ROOT = resolve(import.meta.dirname, "..");
const DATASET_ROOT = resolve(PROJECT_ROOT, "..", "dataset");
const MANIFEST_ROOT = resolve(PROJECT_ROOT, "resources", "manifests", "legacy");
const RUNTIME_DIRECTORY = resolve(PROJECT_ROOT, ".task15-runtime", "qa");
const RUNTIME_PATH = resolve(RUNTIME_DIRECTORY, "index.mjs");
const SCENARIOS = [
  {
    id: "A",
    source: "250725-전남 광양시 아트케이션 관광스테이 확충사업 CCTV 설비 내역서.xlsx",
    sourceSha256:
      "445012e259ab5318a1d52468cce93ee28a55a8bcb467876f40a47a939e4668db",
    manifest: "gwangyang-direct-2025.json",
    itemCount: 16,
    cell: {
      sheet: "자재내역서",
      address: "G9",
      value: { kind: "number", value: "987654" }
    }
  },
  {
    id: "B",
    source: "순천 향교 CCTV 구매 설치 - 내역서(관급)(0706수정).xlsx",
    sourceSha256:
      "2220cd9936ebdf908d64c0571a4c8de83973eaa89c6778a64afec07de7c5e701",
    manifest: "suncheon-procurement-2025.json",
    itemCount: 9,
    cell: {
      sheet: "단가조사",
      address: "H5",
      value: { kind: "number", value: "987654" }
    }
  },
  {
    id: "C",
    source: "전남 광양시 아트케이션 관광스테이 확충사업 CCTV 설비 - 내역서(관급)(최종).xlsx",
    sourceSha256:
      "8a55700bdaf62a00c208c7286531fd56ca321571f73f7620505a823ef5d4d0f1",
    manifest: "gwangyang-procurement-final-2025.json",
    itemCount: 24,
    cell: {
      sheet: "단가조사",
      address: "H5",
      value: { kind: "number", value: "987654" }
    }
  }
];

export async function prepareQaWorkbooks(outputDirectory) {
  const out = resolve(outputDirectory);
  await mkdir(out, { recursive: true });
  const runtime = await loadRuntime();
  try {
    const legacy = [];
    for (const scenario of SCENARIOS) {
      const sourcePath = resolve(DATASET_ROOT, scenario.source);
      const sourceBefore = sha256(await readFile(sourcePath));
      if (sourceBefore !== scenario.sourceSha256) {
        throw new TypeError(`QA_SOURCE_SHA_MISMATCH:${scenario.id}`);
      }
      const manifestBytes = await readFile(
        resolve(MANIFEST_ROOT, scenario.manifest)
      );
      const destinationPath = resolve(
        out,
        `${scenario.id}-${basename(sourcePath, ".xlsx")}_검토초안_미재계산.xlsx`
      );
      const result = await runtime.exportLegacyWorkbook({
        sourcePath,
        destinationPath,
        expectedSourceSha256: scenario.sourceSha256,
        itemCount: scenario.itemCount,
        cells: [scenario.cell],
        manifestBytes,
        generatedAtUtc: "2026-07-23T12:00:00.000Z",
        build: {
          appVersion: "0.1.0",
          commitSha256: "a".repeat(64),
          signed: false
        },
        officialSources: [],
        disclaimer: {
          checked: true,
          version: "legacy-export-disclaimer-v1"
        }
      }, {
        journalRoot: resolve(
          dirname(out),
          `${basename(out)}-journal`,
          scenario.id
        ),
        manifestRoot: pathToFileURL(`${MANIFEST_ROOT}\\`)
      });
      if (!result.ok) {
        throw new TypeError(
          `QA_LEGACY_EXPORT_FAILED:${scenario.id}:${result.error.code}`
        );
      }
      const reportPath = destinationPath.replace(
        /[.]xlsx$/u,
        ".validation.json"
      );
      const report = JSON.parse(await readFile(reportPath, "utf8"));
      const workbook = await verifyWorkbook(destinationPath);
      const sourceAfter = sha256(await readFile(sourcePath));
      if (
        sourceAfter !== sourceBefore ||
        report.validation?.status !== "pass" ||
        workbook.sha256 !== result.workbookSha256 ||
        sha256(await readFile(reportPath)) !== result.validationReportSha256
      ) {
        throw new TypeError(`QA_LEGACY_RECEIPT_FAILED:${scenario.id}`);
      }
      legacy.push({
        id: scenario.id,
        status: "pass",
        sourcePath,
        sourceSha256Before: sourceBefore,
        sourceSha256After: sourceAfter,
        path: destinationPath,
        reportPath,
        outputSha256: result.workbookSha256,
        reportSha256: result.validationReportSha256,
        validationStatus: report.validation.status,
        sheetNames: workbook.sheetNames
      });
    }
    const nativePath = resolve(
      out,
      "native-cctv-lan-fiber-내부검토.xlsx"
    );
    const nativeBytes = await runtime.createNativeWorkbook({
      projectId: "task15-native-qa",
      projectName: "CCTV/LAN/FIBER QA",
      preparedOn: "2026-07-23",
      lines: [],
      koreaNetSelections: []
    });
    await writeFile(nativePath, Buffer.from(nativeBytes));
    const nativeWorkbook = await verifyWorkbook(nativePath);
    if (nativeWorkbook.formulaErrors.length !== 0) {
      throw new TypeError("QA_NATIVE_FORMULA_ERROR");
    }
    const receipt = {
      schemaVersion: "task-15-prepare-receipt-v1",
      status: "pass",
      generatedAtUtc: "2026-07-23T12:00:00.000Z",
      legacy,
      native: {
        status: "pass",
        path: nativePath,
        outputSha256: nativeWorkbook.sha256,
        sheetNames: nativeWorkbook.sheetNames,
        formulaErrors: nativeWorkbook.formulaErrors
      }
    };
    await writeFile(
      resolve(out, "task-15-prepare-receipt.json"),
      `${JSON.stringify(receipt, null, 2)}\n`,
      "utf8"
    );
    return receipt;
  } finally {
    await Promise.all([
      rm(resolve(PROJECT_ROOT, ".task15-runtime"), {
        recursive: true,
        force: true
      }),
      rm(resolve(dirname(out), `${basename(out)}-journal`), {
        recursive: true,
        force: true
      })
    ]);
  }
}

async function loadRuntime() {
  await mkdir(RUNTIME_DIRECTORY, { recursive: true });
  await build({
    stdin: {
      contents: [
        "export { exportLegacyWorkbook } from '../../src/legacy/export/index.ts';",
        "export { createNativeWorkbook } from '../../src/native/workbook.ts';"
      ].join("\n"),
      resolveDir: RUNTIME_DIRECTORY,
      sourcefile: "task15-runtime.ts"
    },
    outfile: RUNTIME_PATH,
    bundle: true,
    external: ["exceljs"],
    format: "esm",
    platform: "node",
    target: "node24"
  });
  return import(`${pathToFileURL(RUNTIME_PATH).href}?qa=${Date.now()}`);
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function cliOutput(args) {
  const index = args.indexOf("--out");
  if (index < 0 || args[index + 1] === undefined) {
    throw new TypeError(
      "Usage: node scripts/prepare-qa-workbooks.mjs --out <directory>"
    );
  }
  return args[index + 1];
}

if (
  process.argv[1] !== undefined &&
  resolve(process.argv[1]) === resolve(import.meta.filename)
) {
  const receipt = await prepareQaWorkbooks(cliOutput(process.argv.slice(2)));
  console.log(JSON.stringify(receipt, null, 2));
}
