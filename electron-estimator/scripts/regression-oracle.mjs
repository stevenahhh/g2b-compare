import { listPackage } from "@electron/asar";
import { createHash } from "node:crypto";
import { access, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import ExcelJS from "exceljs";

const projectRoot = path.resolve(import.meta.dirname, "..");
const evidenceRoot = path.resolve(
  process.env.EVIDENCE_DIR ??
    path.join(projectRoot, "..", ".omo", "evidence", "electron-estimator", "task-17")
);
const matrixRoot = path.resolve(
  process.env.VERIFY_EVIDENCE_ROOT ?? evidenceRoot
);
const workflowRoot = path.join(
  matrixRoot,
  "stages",
  "electron-native-legacy"
);
const unitReportPath = path.join(
  matrixRoot,
  "stages",
  "unit",
  "report.json"
);
const expectedLegacy = [
  {
    profile: "A",
    sourceSha256:
      "445012e259ab5318a1d52468cce93ee28a55a8bcb467876f40a47a939e4668db",
    totalWon: 39_149_530,
    totalSheet: "원가계산서",
    totalCell: "E30"
  },
  {
    profile: "B",
    sourceSha256:
      "2220cd9936ebdf908d64c0571a4c8de83973eaa89c6778a64afec07de7c5e701",
    totalWon: 20_284_000,
    totalSheet: "원가",
    totalCell: "D25"
  },
  {
    profile: "C",
    sourceSha256:
      "8a55700bdaf62a00c208c7286531fd56ca321571f73f7620505a823ef5d4d0f1",
    totalWon: 65_854_000,
    totalSheet: "원가",
    totalCell: "D25"
  }
];
const expectedSeeds = {
  market:
    "607f39517446e9089045ad098bfcb9b998385138f40297b005808785fd59fcb0",
  productivity:
    "567884f2d70c8d15d09f48cd2327ead5146edc6b51dd764a841206395a64f3e6",
  wages:
    "5157a575cc3a9f66c302163bd0f2c4b15c9b3b99e8167834fde89f2b54ae03c7",
  composite:
    "0705bbc698818fd1b291df2c554028253777e10503863fe2564830faf7e3fe16",
  sourceManifest:
    "482309efcfd22ca0cc15dc55c3e08d9b1dc01ae6ef15187946ccdf53fc0f0745"
};

const legacyReceipt = JSON.parse(
  await readFile(path.join(workflowRoot, "task-16-legacy-workflows.json"), "utf8")
);
const legacy = [];
for (const expected of expectedLegacy) {
  const receipt = legacyReceipt.scenarios.find(
    (scenario) => scenario.profile === expected.profile
  );
  if (
    receipt === undefined ||
    receipt.sourceSha256Before !== expected.sourceSha256 ||
    receipt.sourceSha256After !== expected.sourceSha256 ||
    receipt.totalWon !== expected.totalWon ||
    receipt.pairedFiles.length !== 2
  ) {
    throw new TypeError(`ORACLE_LEGACY_RECEIPT_MISMATCH:${expected.profile}`);
  }
  const workbookName = receipt.pairedFiles.find((name) =>
    name.endsWith(".xlsx")
  );
  const reportName = receipt.pairedFiles.find((name) =>
    name.endsWith(".validation.json")
  );
  if (
    workbookName === undefined ||
    reportName === undefined ||
    path.basename(workbookName) !== workbookName ||
    path.basename(reportName) !== reportName
  ) {
    throw new TypeError(`ORACLE_PAIRED_OUTPUT_MISSING:${expected.profile}`);
  }
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.readFile(path.join(workflowRoot, workbookName));
  const cell = workbook
    .getWorksheet(expected.totalSheet)
    ?.getCell(expected.totalCell);
  const totalWon = formulaResult(cell?.value);
  const report = JSON.parse(
    await readFile(path.join(workflowRoot, reportName), "utf8")
  );
  const warnings = report.inherited_warnings.map((warning) => ({
    code: warning.code,
    delta: warning.delta
  }));
  if (
    totalWon !== expected.totalWon ||
    report.validation?.status !== "pass" ||
    warnings.length !== 4 ||
    warnings.some((warning) => warning.delta !== 0)
  ) {
    throw new TypeError(`ORACLE_LEGACY_CONTENT_MISMATCH:${expected.profile}`);
  }
  legacy.push({
    profile: expected.profile,
    totalWon,
    sourceSha256Before: receipt.sourceSha256Before,
    sourceSha256After: receipt.sourceSha256After,
    pairedOutputs: 2,
    inheritedWarningDeltas: warnings
  });
}

const nativeWorkbook = new ExcelJS.Workbook();
await nativeWorkbook.xlsx.readFile(
  path.join(workflowRoot, "task-14-native-workflow.xlsx")
);
const nativeTotalWon = formulaResult(
  nativeWorkbook.getWorksheet("요약")?.getCell("E9").value
);
if (nativeTotalWon !== 143_000) {
  throw new TypeError(`ORACLE_NATIVE_TOTAL_MISMATCH:${String(nativeTotalWon)}`);
}

const sourceManifest = JSON.parse(
  await readFile(
    path.join(projectRoot, "resources", "sources", "source-manifest.json"),
    "utf8"
  )
);
const seedHashes = Object.fromEntries(
  sourceManifest.files.map((dataset) => [dataset.dataset, dataset.sha256])
);
const actualSeeds = {
  market: seedHashes.market,
  productivity: seedHashes.productivity,
  wages: seedHashes.wages,
  composite: sourceManifest.composite_sha256,
  sourceManifest: sourceManifest.source_manifest_sha256
};
if (JSON.stringify(actualSeeds) !== JSON.stringify(expectedSeeds)) {
  throw new TypeError("ORACLE_OFFICIAL_SEED_MISMATCH");
}

const observationManifest = JSON.parse(
  await readFile(
    path.join(projectRoot, "resources", "observations", "manifest.json"),
    "utf8"
  )
);
const observations = JSON.parse(
  await readFile(
    path.join(projectRoot, "resources", "observations", "observations.json"),
    "utf8"
  )
);
if (
  observationManifest.record_count !== 0 ||
  observationManifest.fabricated_rows !== 0 ||
  observations.length !== 0
) {
  throw new TypeError("ORACLE_PRODUCTION_OBSERVATION_NONZERO");
}

const unitReport = JSON.parse(
  await readFile(unitReportPath, "utf8")
);
const passedNames = unitReport.testResults
  .flatMap((result) => result.assertionResults)
  .filter((assertion) => assertion.status === "passed")
  .map((assertion) => assertion.fullName);
const koreaNetMatrix = {
  lowest: passed(passedNames, "KoreaNet is lowest"),
  tied: passed(passedNames, "KoreaNet is tied"),
  lowerCompetitor: passed(
    passedNames,
    "authentic candidate is one won cheaper"
  ),
  specificationFail: passed(
    passedNames,
    "KoreaNet has a specification mismatch"
  ),
  missingEvidence: passed(
    passedNames,
    "KoreaNet is missing location evidence"
  ),
  locationChange: passed(
    passedNames,
    "only location and service statements change"
  )
};
if (Object.values(koreaNetMatrix).some((value) => !value)) {
  throw new TypeError("ORACLE_KOREANET_MATRIX_INCOMPLETE");
}

const archive = path.join(
  projectRoot,
  "release",
  "win-unpacked",
  "resources",
  "app.asar"
);
await access(archive);
const archiveBytes = await readFile(archive);
const archiveEntries = listPackage(archive);
const receipt = {
  schemaVersion: "task-17-regression-oracle-v1",
  status: "pass",
  exportTotals: [
    ...legacy.map(({ profile, totalWon }) => ({ profile, totalWon })),
    { profile: "native", totalWon: nativeTotalWon }
  ],
  legacy,
  officialSeedHashes: actualSeeds,
  koreaNetMatrix,
  productionSyntheticObservationCount: observations.length,
  package: {
    asarEntryCount: archiveEntries.length,
    asarSha256: sha256(archiveBytes),
    testEntryCount: archiveEntries.filter((entry) =>
      /(?:^|\/)(?:test|tests|__tests__)(?:\/|$)/iu.test(
        entry.replaceAll("\\", "/")
      )
    ).length
  }
};
await writeFile(
  path.join(evidenceRoot, "regression-oracle.json"),
  `${JSON.stringify(receipt, null, 2)}\n`,
  "utf8"
);
process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);

function formulaResult(value) {
  if (
    value !== null &&
    typeof value === "object" &&
    "result" in value
  ) {
    return Number(value.result);
  }
  return Number(value);
}

function passed(names, fragment) {
  return names.some((name) => name.includes(fragment));
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}
