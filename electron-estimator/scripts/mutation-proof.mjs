import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { lstat, mkdir, readFile, realpath, writeFile } from "node:fs/promises";
import path from "node:path";
import {
  countOwnedSandboxes, createOwnedSandbox, createSandboxChildEnvironment,
  parseMutationProofArguments, populateOwnedSandbox, recoverOwnedSandboxes,
  removeOwnedSandbox,
  snapshotCopySurface, snapshotProductionSurface
} from "./mutation-sandbox.mjs";

const projectRoot = path.resolve(import.meta.dirname, "..");
const workspaceRoot = path.dirname(projectRoot);
const datasetRoot = path.join(workspaceRoot, "dataset");

const targets = {
  "source-overwrite": {
    relativeFile: path.join("src", "legacy", "export", "paths.ts"),
    replacements: [
      [
        "if (caseInsensitivePath(paths.source) === caseInsensitivePath(paths.workbook)) {",
        "if (false) {"
      ],
      [
        [
          "if (", "      sourceStat.dev === workbookStat.dev &&",
          "      sourceStat.ino === workbookStat.ino", "    ) {"
        ].join("\n"),
        "if (false) {"
      ]
    ],
    evidence: "task-17-mutation-proof.txt"
  },
  "validation-fallback": {
    relativeFile: path.join("src", "legacy", "validation", "report.ts"),
    replacements: [["if (analysis.errors.length > 0) {", "if (false) {"]],
    evidence: "task-17-validation-fallback-mutation-proof.txt"
  }
};
const { targetName, npmArgs } = parseMutationProofArguments(
  process.argv.slice(2)
);
const target = targets[targetName];
if (target === undefined) throw new TypeError("MUTATION_PROOF_TARGET_INVALID");
const { nodeRuntime, npmCli } = await resolveRuntimeCommand();
assertNoOriginalPath([nodeRuntime, npmCli, ...npmArgs]);

const evidenceRoot = path.resolve(process.env.EVIDENCE_DIR ?? path.join(
  workspaceRoot, ".omo", "evidence", "electron-estimator", "task-17",
  "container-sandbox-fix", "mutation"
));
const quarantineRoot = path.join(
  workspaceRoot, ".omo", "evidence", "electron-estimator", "task-17",
  "container-sandbox-fix", "quarantine"
);
await mkdir(evidenceRoot, { recursive: true });
const surfaceBefore = await snapshotProductionSurface(projectRoot, datasetRoot);
const copySurfaceBefore = await snapshotCopySurface(projectRoot, datasetRoot);
const recovered = await recoverOwnedSandboxes(
  workspaceRoot, projectRoot, quarantineRoot
);
const liveAfterRecovery = await countOwnedSandboxes(
  workspaceRoot, projectRoot, quarantineRoot
);
const productionFile = path.join(projectRoot, target.relativeFile);
const original = await readFile(productionFile);
const productionShaBefore = sha256(original);
let mutated = original.toString("utf8");
for (const [from, to] of target.replacements) {
  const next = mutated.replace(from, to);
  if (next === mutated) throw new TypeError(`MUTATION_SEAM_MISSING:${targetName}`);
  mutated = next;
}

const { sandboxRoot, token } = await createOwnedSandbox(
  workspaceRoot, projectRoot, quarantineRoot
);
let red = { exitCode: 1, output: "RED not run\n" };
let green = { exitCode: 1, output: "GREEN not run\n" };
let sandboxTargetMatches = false;
let sandboxRestored = false;
let privateCopyMatches = false;
let sandboxCleaned = false;
let reparsePointCount = -1;
let environmentExposureCount = -1;
let sandboxProjectRoot = "";
let sandboxDatasetRoot = "";
let childEnvironmentKeys = "";
let childEnvironmentPath = "";
let childEnvironmentTemp = "";
let childEnvironmentHome = "";
let executionError = "none";
try {
  const populated = await populateOwnedSandbox(
    sandboxRoot, projectRoot, datasetRoot, quarantineRoot
  );
  ({ sandboxProjectRoot, sandboxDatasetRoot, reparsePointCount } = populated);
  const canonicalSandboxRoot = await realpath(sandboxRoot);
  sandboxProjectRoot = await realpath(sandboxProjectRoot);
  sandboxDatasetRoot = await realpath(sandboxDatasetRoot);
  assertPrivateDirectory(
    sandboxProjectRoot, canonicalSandboxRoot, "electron-estimator"
  );
  assertPrivateDirectory(sandboxDatasetRoot, canonicalSandboxRoot, "dataset");
  const sandboxSurface = await snapshotProductionSurface(
    sandboxProjectRoot, sandboxDatasetRoot
  );
  privateCopyMatches =
    sandboxSurface.digest === copySurfaceBefore.digest &&
    sandboxSurface.fileCount === copySurfaceBefore.fileCount;
  const sandboxFile = path.join(sandboxProjectRoot, target.relativeFile);
  sandboxTargetMatches = sha256(await readFile(sandboxFile)) === productionShaBefore;
  if (!sandboxTargetMatches) throw new TypeError("MUTATION_SANDBOX_SOURCE_MISMATCH");
  const childEnvironment = await createSandboxChildEnvironment({
    sandboxRoot: canonicalSandboxRoot,
    sandboxProjectRoot,
    nodeRuntime
  });
  childEnvironmentKeys = Object.keys(childEnvironment).sort().join(",");
  childEnvironmentPath = childEnvironment.PATH;
  childEnvironmentTemp = childEnvironment.TEMP;
  childEnvironmentHome = childEnvironment.HOME;
  environmentExposureCount = countOriginalPathExposure(childEnvironment);
  await writeFile(sandboxFile, mutated, "utf8");
  red = await runSandbox(npmArgs, sandboxProjectRoot, childEnvironment);
  await writeFile(sandboxFile, original);
  sandboxRestored = sha256(await readFile(sandboxFile)) === productionShaBefore;
  green = await runSandbox(npmArgs, sandboxProjectRoot, childEnvironment);
} catch (error) {
  executionError = error instanceof Error ? error.message : String(error);
} finally {
  await removeOwnedSandbox(
    sandboxRoot, workspaceRoot, projectRoot, token, quarantineRoot
  );
  sandboxCleaned = !(await exists(sandboxRoot));
}

const surfaceAfter = await snapshotProductionSurface(projectRoot, datasetRoot);
const immutableFinalStateChangeCount = changedEntryCount(
  surfaceBefore.manifest, surfaceAfter.manifest
);
const liveAfterCleanup = await countOwnedSandboxes(
  workspaceRoot, projectRoot, quarantineRoot
);
const productionShaAfter = sha256(await readFile(productionFile));
const immutableFinalStateUnchanged =
  productionShaBefore === productionShaAfter &&
  surfaceBefore.digest === surfaceAfter.digest &&
  surfaceBefore.fileCount === surfaceAfter.fileCount &&
  immutableFinalStateChangeCount === 0;
const passed =
  executionError === "none" && red.exitCode !== 0 && green.exitCode === 0 &&
  sandboxTargetMatches && sandboxRestored && privateCopyMatches &&
  sandboxCleaned && reparsePointCount === 0 && environmentExposureCount === 0 &&
  liveAfterRecovery === 0 && liveAfterCleanup === 0 &&
  immutableFinalStateUnchanged;
const receipt = [
  `target=${targetName}`,
  "isolation_mode=private-full-container",
  "isolation_scope=controlled-mutation-command-path-env-cwd",
  "arbitrary_child_os_sandbox=false",
  "command_mode=target-fixed-internal",
  `node_runtime_canonical=${nodeRuntime}`,
  `npm_cli_canonical=${npmCli}`,
  `command_args=${JSON.stringify(npmArgs)}`,
  `container_root=${sandboxRoot}`,
  `child_cwd=${sandboxProjectRoot}`,
  `private_dataset_root=${sandboxDatasetRoot}`,
  "dependencies_mode=private-full-copy",
  `reparse_point_count=${String(reparsePointCount)}`,
  "child_env_mode=fixed-minimal-private",
  "child_env_caller_input_count=0",
  `child_env_keys=${childEnvironmentKeys}`,
  `child_env_path=${childEnvironmentPath}`,
  `child_env_temp=${childEnvironmentTemp}`,
  `child_env_home=${childEnvironmentHome}`,
  `child_env_original_path_exposure_count=${String(environmentExposureCount)}`,
  `recovered_owned_sandboxes=${String(recovered.length)}`,
  `recovered_owned_sandbox_paths=${recovered.map((item) => path.basename(item)).join(",")}`,
  `live_owned_sandboxes_after_recovery=${String(liveAfterRecovery)}`,
  `live_owned_sandboxes_after_cleanup=${String(liveAfterCleanup)}`,
  `RED exit=${String(red.exitCode)} expected_nonzero=true`, red.output,
  `GREEN exit=${String(green.exitCode)} expected_zero=true`, green.output,
  `sandbox_target_pre_sha_match=${String(sandboxTargetMatches)}`,
  `private_copy_manifest_match=${String(privateCopyMatches)}`,
  `sandbox_restored=${String(sandboxRestored)}`,
  `sandbox_cleaned=${String(sandboxCleaned)}`,
  `execution_error=${executionError}`,
  `production_manifest_before_sha256=${surfaceBefore.digest}`,
  `production_manifest_after_sha256=${surfaceAfter.digest}`,
  `production_manifest_before_count=${String(surfaceBefore.fileCount)}`,
  `production_manifest_after_count=${String(surfaceAfter.fileCount)}`,
  `source_sha_before=${productionShaBefore}`,
  `source_sha_after=${productionShaAfter}`,
  "immutable_surface=full-project-and-dataset-final-state",
  `immutable_final_state_change_count=${String(immutableFinalStateChangeCount)}`,
  `mutation_diff0=${String(immutableFinalStateUnchanged)}`,
  `status=${passed ? "pass" : "fail"}`
].join("\n");
await writeFile(path.join(evidenceRoot, target.evidence), `${receipt}\n`, "utf8");
process.stdout.write(`${receipt}\n`);
if (!passed) process.exitCode = 1;

function runSandbox(executableArgs, cwd, environment) {
  return new Promise((resolvePromise) => {
    const child = spawn(
      nodeRuntime,
      [npmCli, ...executableArgs],
      { cwd, env: environment, shell: false }
    );
    let output = "";
    const append = (chunk) => {
      output += String(chunk);
      process.stdout.write(chunk);
    };
    child.stdout.on("data", append);
    child.stderr.on("data", append);
    child.once("error", (error) =>
      resolvePromise({ exitCode: 1, output: `${output}${error.message}\n` })
    );
    child.once("close", (code) =>
      resolvePromise({ exitCode: code ?? 1, output })
    );
  });
}

async function resolveRuntimeCommand() {
  const nodeRuntime = await realpath(process.execPath);
  const runtimeRoot = await realpath(path.dirname(nodeRuntime));
  const npmCli = await realpath(
    path.join(runtimeRoot, "node_modules", "npm", "bin", "npm-cli.js")
  );
  assertContainedPath(npmCli, runtimeRoot, "MUTATION_NPM_CLI_INVALID");
  return { nodeRuntime, npmCli };
}

function changedEntryCount(before, after) {
  const left = new Map(before.map((entry) => [entry.path, JSON.stringify(entry)]));
  const right = new Map(after.map((entry) => [entry.path, JSON.stringify(entry)]));
  let count = 0;
  for (const key of new Set([...left.keys(), ...right.keys()])) {
    if (left.get(key) !== right.get(key)) count += 1;
  }
  return count;
}

function assertNoOriginalPath(values) {
  if (values.some((value) => countOriginalPathExposure({ value }) > 0)) {
    throw new TypeError("MUTATION_COMMAND_ORIGINAL_PATH_EXPOSURE");
  }
}

function assertPrivateDirectory(candidate, sandboxRoot, name) {
  const expected = path.join(sandboxRoot, name);
  if (normalizedPathText(candidate) !== normalizedPathText(expected)) {
    throw new TypeError("MUTATION_CHILD_CWD_INVALID");
  }
  assertContainedPath(candidate, sandboxRoot, "MUTATION_CHILD_CWD_INVALID");
}

function assertContainedPath(candidate, root, code) {
  const relative = path.relative(root, candidate);
  if (
    relative === "" ||
    relative === ".." ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw new TypeError(code);
  }
}

function countOriginalPathExposure(values) {
  const roots = [projectRoot, datasetRoot].map(normalizedPathText);
  return Object.values(values).filter((value) =>
    roots.some((root) => normalizedPathText(value).includes(root))
  ).length;
}

function normalizedPathText(value) {
  return value.replaceAll("/", "\\").toLowerCase();
}

async function exists(candidate) {
  try {
    await lstat(candidate);
    return true;
  } catch (error) {
    const missing = error instanceof Error && "code" in error && error.code === "ENOENT";
    if (missing) return false;
    throw error;
  }
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}
