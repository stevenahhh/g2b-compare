import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import {
  copyFile,
  mkdir,
  readFile,
  readdir,
  stat,
  writeFile
} from "node:fs/promises";
import path from "node:path";
import {
  captureProcessIdentity,
  terminateOwnedProcessTree
} from "./process-tree.mjs";

const projectRoot = path.resolve(import.meta.dirname, "..");
const evidenceRoot = path.resolve(
  process.env.EVIDENCE_DIR ??
    path.join(
      projectRoot,
      "..",
      ".omo",
      "evidence",
      "electron-estimator",
      "task-17",
      `standalone-${randomUUID()}`
    )
);
const reportRoot = path.join(evidenceRoot, "reports");
const runStartedMs = Date.now();
const sharedDefaultRoots = ["task-14", "task-16"].map((task) =>
  path.join(projectRoot, "..", ".omo", "evidence", "electron-estimator", task)
);
const reportToken = "__VERIFY_REPORT_PATH__";
const npmCli = process.env.npm_execpath;
if (npmCli === undefined) {
  throw new TypeError("VERIFY_NPM_CLI_MISSING");
}

const stages = [
  stage("typecheck", "check", npm(["run", "typecheck"]), 120_000),
  stage("build", "check", npm(["run", "build"]), 120_000),
  vitestStage("unit", "vitest.config.ts"),
  vitestStage("integration", "vitest.integration.config.ts", 300_000),
  vitestStage("security", "vitest.security.config.ts"),
  nodeTestStage(),
  playwrightStage("electron-native-legacy"),
  playwrightStage(
    "electron-renderer",
    "tests/renderer/playwright.config.ts"
  ),
  stage("package-asar", "package", npm(["run", "package:dir"]), 300_000),
  stage(
    "artifact-oracle",
    "oracle",
    node(["scripts/regression-oracle.mjs"]),
    120_000
  ),
  stage(
    "cleanup-audit",
    "cleanup",
    node(["scripts/cleanup-audit.mjs"]),
    60_000
  )
];

if (process.argv.includes("--list")) {
  process.stdout.write(
    `${JSON.stringify({
      schemaVersion: "task-17-verify-matrix-v1",
      stages: stages.map(({ id, kind }) => ({ id, kind }))
    })}\n`
  );
} else {
  await runMatrix();
}

async function runMatrix() {
  await requireFreshEvidenceRoot();
  await mkdir(reportRoot, { recursive: true });
  const startedAt = new Date().toISOString();
  const results = [];
  for (const definition of stages) {
    const result = await execute(definition);
    results.push(result);
    if (result.exitCode !== 0) {
      break;
    }
  }
  const testStages = results.filter((result) => result.tests !== null);
  const totals = testStages.reduce(
    (sum, result) => ({
      tests: sum.tests + result.tests.total,
      passed: sum.passed + result.tests.passed,
      failed: sum.failed + result.tests.failed,
      skipped: sum.skipped + result.tests.skipped,
      pending: sum.pending + result.tests.pending
    }),
    { tests: 0, passed: 0, failed: 0, skipped: 0, pending: 0 }
  );
  const complete = results.length === stages.length;
  const sharedDefaultWrites = (
    await Promise.all(
      sharedDefaultRoots.map((root) => filesModifiedSince(root, runStartedMs))
    )
  ).flat();
  const passed =
    complete &&
    results.every((result) => result.exitCode === 0) &&
    totals.tests > 0 &&
    totals.failed === 0 &&
    totals.skipped === 0 &&
    totals.pending === 0 &&
    sharedDefaultWrites.length === 0;
  const summary = {
    schemaVersion: "task-17-verify-summary-v1",
    status: passed ? "pass" : "fail",
    startedAt,
    finishedAt: new Date().toISOString(),
    stageCount: stages.length,
    executedStageCount: results.length,
    sharedDefaultWriteCount: sharedDefaultWrites.length,
    sharedDefaultWrites,
    totals,
    stages: results
  };
  await Promise.all([
    writeFile(
      path.join(evidenceRoot, "verify-all-summary.json"),
      `${JSON.stringify(summary, null, 2)}\n`,
      "utf8"
    ),
    writeFile(
      path.join(evidenceRoot, "verify-all.junit.xml"),
      junit(summary),
      "utf8"
    )
  ]);
  process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
  if (!passed) {
    process.exitCode = 1;
  }
}

async function requireFreshEvidenceRoot() {
  try {
    const existing = await readdir(evidenceRoot);
    if (existing.length !== 0) {
      throw new TypeError("VERIFY_EVIDENCE_ROOT_NOT_EMPTY");
    }
  } catch (error) {
    if (
      !(error instanceof Error) ||
      !("code" in error) ||
      error.code !== "ENOENT"
    ) {
      throw error;
    }
  }
}

async function execute(definition) {
  process.stdout.write(`\n[verify:all] ${definition.id}\n`);
  const started = Date.now();
  const stageEvidenceRoot = path.join(evidenceRoot, "stages", definition.id);
  await mkdir(stageEvidenceRoot, { recursive: true });
  const reportPath =
    definition.reportFile === null
      ? null
      : path.join(stageEvidenceRoot, definition.reportFile);
  const environment = {
    ...process.env,
    EVIDENCE_DIR: stageEvidenceRoot,
    VERIFY_EVIDENCE_ROOT: evidenceRoot,
    VERIFY_RUN_STARTED_MS: String(runStartedMs),
    ...(reportPath === null ||
    definition.reportEnvironment.length === 0
      ? {}
      : { [definition.reportEnvironment]: reportPath })
  };
  const args = definition.args.map((argument) =>
    reportPath === null ? argument : argument.replace(reportToken, reportPath)
  );
  const result = await run(definition.command, args, {
    environment,
    timeoutMs: definition.timeoutMs
  });
  const logPath = path.join(evidenceRoot, `${definition.id}.log`);
  await writeFile(logPath, result.output, "utf8");
  const tests =
    definition.reportKind === "vitest"
      ? await vitestFacts(reportPath)
      : definition.reportKind === "playwright"
        ? await playwrightFacts(reportPath)
        : definition.reportKind === "tap"
          ? tapFacts(result.output)
          : null;
  if (reportPath !== null) {
    await copyFile(reportPath, path.join(reportRoot, `${definition.id}.json`));
  }
  if (definition.id === "artifact-oracle" && result.exitCode === 0) {
    await copyFile(
      path.join(stageEvidenceRoot, "regression-oracle.json"),
      path.join(evidenceRoot, "regression-oracle.json")
    );
  }
  if (definition.id === "cleanup-audit" && result.exitCode === 0) {
    await copyFile(
      path.join(stageEvidenceRoot, "cleanup-audit.json"),
      path.join(evidenceRoot, "cleanup-audit.json")
    );
  }
  const semanticExit =
    tests !== null &&
    (tests.total === 0 ||
      tests.failed !== 0 ||
      tests.skipped !== 0 ||
      tests.pending !== 0)
      ? 1
      : result.exitCode;
  if (
    definition.id === "package-asar" &&
    (!result.output.includes("PACKAGE_INVENTORY_PASS") ||
      !result.output.includes("PACKAGE_RUNTIME_SMOKE_PASS"))
  ) {
    return resultRecord(
      definition,
      1,
      started,
      tests,
      logPath,
      stageEvidenceRoot,
      result
    );
  }
  return resultRecord(
    definition,
    semanticExit,
    started,
    tests,
    logPath,
    stageEvidenceRoot,
    result
  );
}

function resultRecord(
  definition,
  exitCode,
  started,
  tests,
  logPath,
  evidenceDirectory,
  execution
) {
  return {
    id: definition.id,
    kind: definition.kind,
    exitCode,
    durationMs: Date.now() - started,
    tests,
    timedOut: execution.timedOut,
    processTree: execution.processTree,
    evidenceDirectory: path
      .relative(projectRoot, evidenceDirectory)
      .replaceAll("\\", "/"),
    logPath: path.relative(projectRoot, logPath).replaceAll("\\", "/")
  };
}

function run(command, args, options) {
  return new Promise((resolvePromise) => {
    const child = spawn(command, args, {
      cwd: projectRoot,
      env: options.environment,
      shell: false
    });
    let output = "";
    let finished = false;
    let timedOut = false;
    let termination = Promise.resolve(null);
    const rootIdentity = process.platform === "win32"
      ? captureProcessIdentity(child.pid).catch(() => null)
      : Promise.resolve(null);
    const timer = setTimeout(() => {
      timedOut = true;
      termination = rootIdentity.then((identity) => {
        if (process.platform === "win32" && identity === null) {
          throw new TypeError("PROCESS_TREE_ROOT_IDENTITY_MISSING");
        }
        return terminateOwnedProcessTree(identity ?? child.pid);
      });
    }, options.timeoutMs);
    const append = (chunk) => {
      output += String(chunk);
      process.stdout.write(chunk);
    };
    child.stdout.on("data", append);
    child.stderr.on("data", append);
    child.once("error", (error) => {
      if (!finished) {
        finished = true;
        clearTimeout(timer);
        resolvePromise({
          exitCode: 1,
          output: `${output}${error.message}\n`,
          timedOut,
          processTree: null
        });
      }
    });
    child.once("close", async (code) => {
      if (!finished) {
        try {
          const processTree = await termination;
          finished = true;
          clearTimeout(timer);
          resolvePromise({
            exitCode: timedOut ? 124 : (code ?? 1),
            output,
            timedOut,
            processTree
          });
        } catch (error) {
          finished = true;
          clearTimeout(timer);
          resolvePromise({
            exitCode: 1,
            output: `${output}${error instanceof Error ? error.message : String(error)}\n`,
            timedOut,
            processTree: null
          });
        }
      }
    });
  });
}

async function vitestFacts(reportPath) {
  const report = JSON.parse(await readFile(reportPath, "utf8"));
  return {
    total: report.numTotalTests,
    passed: report.numPassedTests,
    failed: report.numFailedTests,
    skipped: report.numPendingTests,
    pending: report.numTodoTests
  };
}

async function playwrightFacts(reportPath) {
  const report = JSON.parse(await readFile(reportPath, "utf8"));
  const specifications = report.suites.flatMap(flattenSuite);
  const tests = specifications.flatMap((specification) => specification.tests);
  const skipped = tests.filter(
    (testCase) => testCase.expectedStatus === "skipped"
  ).length;
  const pending = tests.filter(
    (testCase) =>
      testCase.results.length === 0 && testCase.expectedStatus !== "skipped"
  ).length;
  const failed = tests.filter((testCase) =>
    testCase.results.some((result) => result.status !== "passed")
  ).length;
  return {
    total: tests.length,
    passed: tests.length - failed - skipped - pending,
    failed,
    skipped,
    pending
  };
}

function flattenSuite(suite) {
  return [
    ...(suite.specs ?? []),
    ...(suite.suites ?? []).flatMap(flattenSuite)
  ];
}

function tapFacts(output) {
  const value = (label) => {
    const match = output.match(new RegExp(`^# ${label} (\\d+)$`, "mu"));
    return match === null ? 0 : Number(match[1]);
  };
  return {
    total: value("tests"),
    passed: value("pass"),
    failed: value("fail"),
    skipped: value("skipped"),
    pending: value("todo")
  };
}

function stage(id, kind, invocation, timeoutMs) {
  return {
    id,
    kind,
    ...invocation,
    timeoutMs,
    reportKind: null,
    reportFile: null,
    reportEnvironment: ""
  };
}

function vitestStage(id, config, timeoutMs = 120_000) {
  return {
    ...stage(
      id,
      "test",
      npm([
        "exec",
        "--",
        "vitest",
        "--config",
        config,
        "--run",
        "--reporter=json",
        `--outputFile=${reportToken}`
      ]),
      timeoutMs
    ),
    reportKind: "vitest",
    reportFile: "report.json",
    reportEnvironment: ""
  };
}

function nodeTestStage() {
  return {
    ...stage(
      "data-contracts-legacy",
      "test",
      node([
        "--test",
        "--test-reporter=tap",
        "tests/contracts/*.test.mjs",
        "tests/data/*.test.mjs",
        "tests/legacy/*.test.mjs"
      ]),
      180_000
    ),
    reportKind: "tap"
  };
}

function playwrightStage(id, config) {
  return {
    ...stage(
      id,
      "test",
      npm([
        "exec",
        "--",
        "playwright",
        "test",
        ...(config === undefined ? [] : [`--config=${config}`]),
        "--reporter=json"
      ]),
      300_000
    ),
    reportKind: "playwright",
    reportFile: "report.json",
    reportEnvironment: "PLAYWRIGHT_JSON_OUTPUT_FILE"
  };
}

function npm(args) {
  return { command: process.execPath, args: [npmCli, ...args] };
}

function node(args) {
  return { command: process.execPath, args };
}

function junit(summary) {
  const failures = summary.stages.filter((item) => item.exitCode !== 0);
  const cases = summary.stages
    .map((item) => {
      const failure =
        item.exitCode === 0
          ? ""
          : `<failure message="exit ${String(item.exitCode)}"/>`;
      return `<testcase name="${escapeXml(item.id)}" time="${(
        item.durationMs / 1000
      ).toFixed(3)}">${failure}</testcase>`;
    })
    .join("");
  return (
    `<?xml version="1.0" encoding="UTF-8"?>` +
    `<testsuite name="task-17-verify-all" tests="${String(
      summary.stages.length
    )}" failures="${String(failures.length)}" skipped="${String(
      summary.totals.skipped + summary.totals.pending
    )}">${cases}</testsuite>\n`
  );
}

function escapeXml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function filesModifiedSince(directory, startedMs) {
  let entries;
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch (error) {
    if (
      error instanceof Error &&
      "code" in error &&
      error.code === "ENOENT"
    ) {
      return [];
    }
    throw error;
  }
  const modified = [];
  for (const entry of entries) {
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      modified.push(...(await filesModifiedSince(candidate, startedMs)));
    } else if ((await stat(candidate)).mtimeMs >= startedMs) {
      modified.push(path.relative(projectRoot, candidate).replaceAll("\\", "/"));
    }
  }
  return modified;
}
