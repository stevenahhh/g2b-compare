import { spawn } from "node:child_process";
import { lstat, readdir, rename, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const PRODUCT_RESIDUE_NAMES = [".debug-journal.md", ".tmp-legacy-import.mjs", "$log"];
const MUTATION_SANDBOX = /^\.electron-estimator-task17-mutation-[0-9a-f-]{36}$/u;
const TEMP_DIRECTORY = /^electron-estimator-(?:atomic|legacy|smoke|native|recovery)-/u;
const ADJACENT_RESIDUE = /\.task17-.*\.(?:backup|observed)$/u;

export async function findFilesystemResidue(options) {
  const { projectRoot, workspaceRoot, matrixRoot, tempRoot } = options;
  const { managedJournalRoot, mutationGuardRoot, taskEvidenceRoot } = options;
  const paths = [
    ...(await existingProductResidue(projectRoot)),
    ...(await matchingChildren(workspaceRoot,
      (name) => MUTATION_SANDBOX.test(name))),
    ...(await adjacentMutationResidue(projectRoot)),
    ...(await matchingChildren(tempRoot, (name) =>
      name !== path.basename(managedJournalRoot) &&
      TEMP_DIRECTORY.test(name))),
    ...(await journalResidue(managedJournalRoot)),
    ...(await journalResidue(mutationGuardRoot)),
    ...(await findStagingPaths(taskEvidenceRoot)),
    ...(await findTemporaryFiles(matrixRoot, path.join(matrixRoot, "quarantine")))
  ];
  return [...new Set(paths.map((candidate) => path.resolve(candidate)))].sort();
}

async function runAudit() {
  const projectRoot = path.resolve(import.meta.dirname, "..");
  const workspaceRoot = path.dirname(projectRoot);
  const evidenceRoot = path.resolve(process.env.EVIDENCE_DIR ??
    path.join(workspaceRoot, ".omo", "evidence", "electron-estimator",
      "task-17"));
  const matrixRoot = path.resolve(process.env.VERIFY_EVIDENCE_ROOT ?? evidenceRoot);
  const taskEvidenceRoot = path.basename(matrixRoot) === "task-17"
    ? matrixRoot : path.dirname(matrixRoot);
  const workflowRoot =
    path.join(matrixRoot, "stages", "electron-native-legacy");
  const managedJournalRoot =
    path.join(tmpdir(), "electron-estimator-atomic-export-journal");
  const mutationGuardRoot =
    path.join(tmpdir(), "electron-estimator-task17-mutation-guard");
  const electronProcesses = JSON.parse(
    await powershell(
      [
        "$root=$env:VERIFY_PROJECT_ROOT",
        "$items=Get-CimInstance Win32_Process | Where-Object {",
        "($_.Name -match '^(electron|Electron Estimator)[.]exe$') -and",
        "$_.CommandLine -and $_.CommandLine.Contains($root)",
        "} | Select-Object ProcessId,Name,CommandLine",
        "ConvertTo-Json -InputObject @($items) -Compress"
      ].join("\n"),
      projectRoot
    )
  );
  const temporaryPaths = await findFilesystemResidue(
    { projectRoot, workspaceRoot, matrixRoot, tempRoot: tmpdir(),
      managedJournalRoot, mutationGuardRoot, taskEvidenceRoot }
  );
  const workbookPaths = (await readdir(workflowRoot))
    .filter((name) =>
      name.endsWith(".xlsx") || name.endsWith(".validation.json"))
    .map((name) => path.join(workflowRoot, name));
  const openFileCount = await countOpenFiles(workbookPaths);
  const productResiduePaths = temporaryPaths.filter(
    (candidate) =>
      path.dirname(candidate) === projectRoot &&
      PRODUCT_RESIDUE_NAMES.includes(path.basename(candidate))
  );
  const receipt = {
    schemaVersion: "task-17-cleanup-audit-v1",
    status:
      electronProcesses.length === 0 &&
      openFileCount === 0 &&
      temporaryPaths.length === 0
        ? "pass"
        : "fail",
    electronProcessCount: electronProcesses.length,
    electronProcesses,
    openFileCount,
    filesProbed: workbookPaths.length,
    productResidueCount: productResiduePaths.length,
    productResiduePaths,
    temporaryExportCount: temporaryPaths.length,
    temporaryPaths,
    capabilityCount: 0,
    capabilityBasis: "process-scoped stores destroyed with zero app processes"
  };
  await writeFile(path.join(evidenceRoot, "cleanup-audit.json"),
    `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
  if (receipt.status !== "pass") {
    process.exitCode = 1;
  }
}

async function existingProductResidue(projectRoot) {
  const paths = [];
  for (const name of PRODUCT_RESIDUE_NAMES) {
    const candidate = path.join(projectRoot, name);
    if (await exists(candidate)) {
      paths.push(candidate);
    }
  }
  return paths;
}

async function matchingChildren(directory, predicate) {
  const paths = [];
  for (const name of await readdir(directory)) {
    if (predicate(name)) {
      paths.push(path.join(directory, name));
    }
  }
  return paths;
}

async function findStagingPaths(directory) {
  const paths = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const candidate = path.join(directory, entry.name);
    if (entry.name.startsWith(".staging-")) paths.push(candidate);
    else if (entry.isDirectory() && !entry.isSymbolicLink())
      paths.push(...(await findStagingPaths(candidate)));
  }
  return paths;
}

async function findTemporaryFiles(directory, retainedQuarantineRoot) {
  const entries = await readdir(directory, { withFileTypes: true });
  const paths = [];
  for (const entry of entries) {
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      if (path.resolve(candidate) === path.resolve(retainedQuarantineRoot)) {
        continue;
      }
      if (
        entry.name.startsWith(".staging-") ||
        MUTATION_SANDBOX.test(entry.name) ||
        /journal/iu.test(entry.name)
      ) {
        paths.push(candidate);
      } else {
        paths.push(...(await findTemporaryFiles(candidate, retainedQuarantineRoot)));
      }
    } else if (
      entry.name.endsWith(".tmp") ||
      entry.name.startsWith(".tmp-") ||
      entry.name === ".debug-journal.md" ||
      entry.name === "$log" ||
      ADJACENT_RESIDUE.test(entry.name)
    ) {
      paths.push(candidate);
    }
  }
  return paths;
}

async function adjacentMutationResidue(projectRoot) {
  const directories = [
    path.join(projectRoot, "src", "legacy", "export"),
    path.join(projectRoot, "src", "legacy", "validation")
  ];
  return (await Promise.all(directories.map((directory) =>
    matchingChildren(directory, (name) => ADJACENT_RESIDUE.test(name))
  ))).flat();
}

async function journalResidue(directory) {
  if (!(await exists(directory))) {
    return [];
  }
  return (await readdir(directory)).map((name) => path.join(directory, name));
}

async function countOpenFiles(workbookPaths) {
  let openFileCount = 0;
  for (const file of workbookPaths) {
    const probe = `${file}.open-audit`;
    try {
      await rename(file, probe);
      await rename(probe, file);
    } catch (error) {
      openFileCount += 1;
      if (await exists(probe)) {
        await rename(probe, file);
      }
      if (!(error instanceof Error)) {
        throw error;
      }
    }
  }
  return openFileCount;
}

function powershell(script, projectRoot) {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn("powershell.exe",
      ["-NoProfile", "-NonInteractive", "-Command", script],
      {
        cwd: projectRoot,
        env: { ...process.env, VERIFY_PROJECT_ROOT: projectRoot },
        shell: false
      });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.once("error", rejectPromise);
    child.once("close", (code) => {
      if (code !== 0) {
        rejectPromise(new TypeError(
          `CLEANUP_PROCESS_QUERY_FAILED:${stderr.trim()}`
        ));
      } else {
        resolvePromise(stdout.trim() || "[]");
      }
    });
  });
}

async function exists(candidate) {
  try {
    await lstat(candidate);
    return true;
  } catch (error) {
    if (
      error instanceof Error &&
      "code" in error &&
      error.code === "ENOENT"
    ) {
      return false;
    }
    throw error;
  }
}

const invokedFile = process.argv[1];
if (invokedFile !== undefined && import.meta.url === pathToFileURL(path.resolve(invokedFile)).href) {
  await runAudit();
}
