import { createHash, randomUUID } from "node:crypto";
import {
  cp, lstat, mkdir, open, readFile, readdir, readlink, realpath, rename, rm,
  unlink, writeFile
} from "node:fs/promises";
import path from "node:path";

const PREFIX = ".electron-estimator-task17-mutation-";
const MARKER = ".task17-mutation-sandbox.json";
const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
const NAME = new RegExp(`^\\${PREFIX}${UUID}$`, "u");
const STAGING_NAME = new RegExp(`^\\.staging-${UUID}$`, "u");
const OWNER_NAME = new RegExp(`^\\.task17-owner-(${UUID})\\.json$`, "u");
const MARKER_KEYS = ["containerName", "schemaVersion", "stagingName", "token"];
const JOURNAL_KEYS = [
  "markerSha256", "projectRoot", "quarantineRoot", "sandboxRoot",
  "schemaVersion", "stagingRoot", "token", "workspaceRoot"
];
const MUTATION_COMMANDS = new Map([
  [
    "source-overwrite",
    [
      "run", "test:integration", "--", "--run",
      "tests/integration/atomic-export.test.ts"
    ]
  ],
  [
    "validation-fallback",
    [
      "run", "test:integration", "--", "--run",
      "tests/integration/validation-report-negative.test.ts"
    ]
  ]
]);

export function parseMutationProofArguments(args) {
  if (
    args.length !== 2 ||
    args[0] !== "--target" ||
    !MUTATION_COMMANDS.has(args[1])
  ) {
    throw new TypeError("MUTATION_PROOF_ARGUMENTS_INVALID");
  }
  return {
    targetName: args[1],
    npmArgs: [...MUTATION_COMMANDS.get(args[1])]
  };
}

export async function createOwnedSandbox(workspaceRoot, projectRoot, quarantineRoot) {
  await assertSafeDirectory(workspaceRoot);
  await assertContainedDirectory(projectRoot, workspaceRoot);
  await ensureContainedDirectory(quarantineRoot, workspaceRoot);
  await assertNoReparsePoints(projectRoot);
  const token = randomUUID();
  const sandboxRoot = path.join(workspaceRoot, `${PREFIX}${randomUUID()}`);
  const stagingRoot = path.join(quarantineRoot, `.staging-${randomUUID()}`);
  const marker = markerFor(token, sandboxRoot, stagingRoot);
  const journal = {
    schemaVersion: "task-17-mutation-owner-v1",
    token,
    workspaceRoot: path.resolve(workspaceRoot),
    projectRoot: path.resolve(projectRoot),
    quarantineRoot: path.resolve(quarantineRoot),
    sandboxRoot: path.resolve(sandboxRoot),
    stagingRoot: path.resolve(stagingRoot),
    markerSha256: sha256(markerBytes(marker))
  };
  await atomicWriteJournal(ownerPath(quarantineRoot, token), journal);
  await mkdir(stagingRoot);
  await writeFile(path.join(stagingRoot, MARKER), markerBytes(marker), {
    encoding: "utf8",
    flag: "wx"
  });
  await assertSafeDirectory(stagingRoot);
  await rename(stagingRoot, sandboxRoot);
  return { sandboxRoot, token };
}

export async function populateOwnedSandbox(
  sandboxRoot, projectRoot, datasetRoot, quarantineRoot
) {
  const workspaceRoot = path.dirname(path.resolve(sandboxRoot));
  const inputsContained =
    path.dirname(path.resolve(projectRoot)) === workspaceRoot &&
    path.basename(projectRoot) === "electron-estimator" &&
    path.dirname(path.resolve(datasetRoot)) === workspaceRoot &&
    path.basename(datasetRoot) === "dataset";
  if (!inputsContained) {
    throw new TypeError("MUTATION_SANDBOX_INPUT_CONTAINMENT_INVALID");
  }
  await assertContainedDirectory(projectRoot, workspaceRoot);
  await assertContainedDirectory(datasetRoot, workspaceRoot);
  await assertContainedDirectory(quarantineRoot, workspaceRoot);
  await assertNoReparsePoints(projectRoot);
  await assertNoReparsePoints(datasetRoot);
  const owned = await readOwnedContext(
    sandboxRoot, workspaceRoot, projectRoot, quarantineRoot
  );
  if (owned === null) throw new TypeError("MUTATION_SANDBOX_OWNERSHIP_INVALID");
  const sandboxProjectRoot = path.join(sandboxRoot, "electron-estimator");
  const sandboxDatasetRoot = path.join(sandboxRoot, "dataset");
  await copyProject(projectRoot, sandboxProjectRoot);
  await cp(datasetRoot, sandboxDatasetRoot, {
    recursive: true,
    dereference: true,
    errorOnExist: true
  });
  await assertNoReparsePoints(sandboxProjectRoot);
  await assertNoReparsePoints(sandboxDatasetRoot);
  return { sandboxProjectRoot, sandboxDatasetRoot, reparsePointCount: 0 };
}

export async function recoverOwnedSandboxes(
  workspaceRoot, projectRoot, quarantineRoot
) {
  await assertSafeDirectory(workspaceRoot);
  await ensureContainedDirectory(quarantineRoot, workspaceRoot);
  const recovered = [];
  for (const entry of await readdir(quarantineRoot, { withFileTypes: true })) {
    if (!entry.isFile() || !OWNER_NAME.test(entry.name)) continue;
    const journalPath = path.join(quarantineRoot, entry.name);
    const journal = await readJournal(journalPath);
    if (!validJournal(
      journal, journalPath, workspaceRoot, projectRoot, quarantineRoot
    )) continue;
    const sandboxExists = await isSafeDirectory(journal.sandboxRoot);
    const stagingExists = await isSafeDirectory(journal.stagingRoot);
    let candidate;
    let type;
    if (sandboxExists) {
      const marker = await readMarker(journal.sandboxRoot);
      if (!markerMatchesJournal(marker, journal)) continue;
      candidate = journal.sandboxRoot;
      type = "container";
    } else if (stagingExists) {
      candidate = journal.stagingRoot;
      type = "staging";
    } else {
      await archiveJournal(journalPath, quarantineRoot, journal.token);
      continue;
    }
    await assertSafeDirectory(candidate);
    const destination = path.join(
      quarantineRoot,
      `stale-${type}-${path.basename(candidate)}-${randomUUID()}`
    );
    await rename(candidate, destination);
    await assertSafeDirectory(destination);
    if (
      type === "container" &&
      !markerMatchesJournal(await readMarker(destination), journal)
    ) continue;
    await archiveJournal(journalPath, quarantineRoot, journal.token);
    recovered.push(destination);
  }
  return recovered;
}

export async function countOwnedSandboxes(
  workspaceRoot, projectRoot, quarantineRoot
) {
  await ensureContainedDirectory(quarantineRoot, workspaceRoot);
  let count = 0;
  for (const entry of await readdir(quarantineRoot, { withFileTypes: true })) {
    if (!entry.isFile() || !OWNER_NAME.test(entry.name)) continue;
    const journalPath = path.join(quarantineRoot, entry.name);
    const journal = await readJournal(journalPath);
    if (
      validJournal(journal, journalPath, workspaceRoot, projectRoot, quarantineRoot) &&
      await isSafeDirectory(journal.sandboxRoot) &&
      markerMatchesJournal(await readMarker(journal.sandboxRoot), journal)
    ) count += 1;
  }
  return count;
}

export async function removeOwnedSandbox(
  sandboxRoot, workspaceRoot, projectRoot, token, quarantineRoot
) {
  const owned = await readOwnedContext(
    sandboxRoot, workspaceRoot, projectRoot, quarantineRoot
  );
  if (owned === null || owned.journal.token !== token) {
    throw new TypeError("MUTATION_SANDBOX_OWNERSHIP_INVALID");
  }
  await assertSafeDirectory(sandboxRoot);
  const tombstone = path.join(
    quarantineRoot, `.cleanup-${token}-${randomUUID()}`
  );
  await rename(sandboxRoot, tombstone);
  await assertSafeDirectory(tombstone);
  if (!markerMatchesJournal(await readMarker(tombstone), owned.journal)) {
    throw new TypeError("MUTATION_SANDBOX_POSTCLAIM_INVALID");
  }
  await rm(tombstone, { recursive: true, force: false });
  await unlink(owned.journalPath);
}

export async function snapshotProductionSurface(projectRoot, datasetRoot) {
  return snapshotTrees(projectRoot, datasetRoot);
}

export async function snapshotCopySurface(projectRoot, datasetRoot) {
  return snapshotTrees(projectRoot, datasetRoot);
}

export async function createSandboxChildEnvironment({
  sandboxRoot,
  sandboxProjectRoot,
  nodeRuntime
}) {
  await assertSafeDirectory(sandboxRoot);
  await assertContainedDirectory(sandboxProjectRoot, sandboxRoot);
  const canonicalSandboxRoot = await realpath(sandboxRoot);
  const canonicalProjectRoot = await realpath(sandboxProjectRoot);
  if (
    caseInsensitive(canonicalProjectRoot) !==
    caseInsensitive(path.join(canonicalSandboxRoot, "electron-estimator"))
  ) {
    throw new TypeError("MUTATION_CHILD_ENV_PROJECT_INVALID");
  }
  const binaryRoot = await realpath(
    path.join(canonicalProjectRoot, "node_modules", ".bin")
  );
  if (!isContainedOrEqual(canonicalProjectRoot, binaryRoot)) {
    throw new TypeError("MUTATION_CHILD_ENV_BINARY_PATH_INVALID");
  }
  const canonicalNodeRuntime = await realpath(nodeRuntime);
  const runtimeRoot = await realpath(path.dirname(canonicalNodeRuntime));
  const windowsRoot = await realpath(
    path.join(path.parse(canonicalNodeRuntime).root, "Windows")
  );
  const system32 = await realpath(path.join(windowsRoot, "System32"));
  const comspec = await realpath(path.join(system32, "cmd.exe"));
  if (
    path.basename(windowsRoot).toLowerCase() !== "windows" ||
    !isContainedOrEqual(windowsRoot, system32) ||
    !isContainedOrEqual(system32, comspec) ||
    !(await lstat(comspec)).isFile()
  ) {
    throw new TypeError("MUTATION_CHILD_ENV_WINDOWS_RUNTIME_INVALID");
  }
  const privateRoot = path.join(canonicalSandboxRoot, ".child-env");
  const privateTemp = path.join(privateRoot, "temp");
  const privateHome = path.join(privateRoot, "home");
  await mkdir(privateTemp, { recursive: true });
  await mkdir(privateHome, { recursive: true });
  await assertContainedDirectory(privateTemp, canonicalSandboxRoot);
  await assertContainedDirectory(privateHome, canonicalSandboxRoot);
  return {
    COMSPEC: comspec,
    HOME: privateHome,
    PATH: [binaryRoot, runtimeRoot, system32].join(path.delimiter),
    PATHEXT: ".COM;.EXE;.BAT;.CMD",
    SYSTEMROOT: windowsRoot,
    TEMP: privateTemp,
    TMP: privateTemp,
    USERPROFILE: privateHome,
    WINDIR: windowsRoot
  };
}

async function snapshotTrees(projectRoot, datasetRoot) {
  await assertSafeDirectory(projectRoot);
  await assertSafeDirectory(datasetRoot);
  const manifest = [];
  await appendManifest(projectRoot, "project", manifest);
  await appendManifest(datasetRoot, "dataset", manifest);
  manifest.sort((left, right) => left.path.localeCompare(right.path, "en"));
  const serialized = manifest.map((entry) =>
    `${entry.path}\0${entry.kind}\0${entry.size}\0${entry.sha256}\n`
  ).join("");
  return {
    digest: sha256(Buffer.from(serialized)),
    fileCount: manifest.length,
    manifest
  };
}

async function copyProject(projectRoot, destination) {
  await mkdir(destination);
  for (const entry of await readdir(projectRoot, { withFileTypes: true })) {
    await cp(path.join(projectRoot, entry.name), path.join(destination, entry.name), {
      recursive: true,
      dereference: true,
      errorOnExist: true
    });
  }
}

async function appendManifest(root, namespace, manifest) {
  for (const entry of await readdir(root, { withFileTypes: true })) {
    await appendEntry(
      path.join(root, entry.name), `${namespace}/${entry.name}`, manifest
    );
  }
}

async function appendEntry(absolute, relative, manifest) {
  const stats = await lstat(absolute);
  if (stats.isDirectory()) {
    manifest.push({
      path: relative.replaceAll("\\", "/"),
      kind: "directory",
      size: 0,
      sha256: sha256(Buffer.alloc(0))
    });
    for (const entry of await readdir(absolute, { withFileTypes: true })) {
      await appendEntry(
        path.join(absolute, entry.name), `${relative}/${entry.name}`, manifest
      );
    }
    return;
  }
  const content = stats.isSymbolicLink()
    ? Buffer.from(await readlink(absolute), "utf8")
    : await readFile(absolute);
  manifest.push({
    path: relative.replaceAll("\\", "/"),
    kind: stats.isSymbolicLink() ? "reparse" : "file",
    size: content.length,
    sha256: sha256(content)
  });
}

async function readOwnedContext(
  sandboxRoot, workspaceRoot, projectRoot, quarantineRoot
) {
  await assertSafeDirectory(workspaceRoot);
  await assertContainedDirectory(projectRoot, workspaceRoot);
  await assertContainedDirectory(quarantineRoot, workspaceRoot);
  const marker = await readMarker(sandboxRoot);
  if (marker === null || !validMarkerShape(marker)) return null;
  const journalPath = ownerPath(quarantineRoot, marker.token);
  const journal = await readJournal(journalPath);
  if (
    !validJournal(journal, journalPath, workspaceRoot, projectRoot, quarantineRoot) ||
    path.resolve(journal.sandboxRoot) !== path.resolve(sandboxRoot) ||
    !markerMatchesJournal(marker, journal) ||
    !(await isSafeDirectory(sandboxRoot))
  ) return null;
  return { journal, journalPath };
}

async function atomicWriteJournal(journalPath, journal) {
  const temporary = `${journalPath}.${randomUUID()}.tmp`;
  const handle = await open(temporary, "wx");
  try {
    await handle.writeFile(`${JSON.stringify(journal)}\n`, "utf8");
    await handle.sync();
  } finally {
    await handle.close();
  }
  await rename(temporary, journalPath);
}

async function archiveJournal(journalPath, quarantineRoot, token) {
  await rename(
    journalPath,
    path.join(quarantineRoot, `stale-journal-${token}-${randomUUID()}.json`)
  );
}

async function readJournal(journalPath) {
  try {
    const stats = await lstat(journalPath);
    if (!stats.isFile() || stats.isSymbolicLink()) return null;
    return JSON.parse(await readFile(journalPath, "utf8"));
  } catch {
    return null;
  }
}

async function readMarker(root) {
  try {
    const rootStats = await lstat(root);
    const markerPath = path.join(root, MARKER);
    const markerStats = await lstat(markerPath);
    if (
      !rootStats.isDirectory() || rootStats.isSymbolicLink() ||
      !markerStats.isFile() || markerStats.isSymbolicLink()
    ) return null;
    return JSON.parse(await readFile(markerPath, "utf8"));
  } catch {
    return null;
  }
}

function validJournal(
  journal, journalPath, workspaceRoot, projectRoot, quarantineRoot
) {
  if (
    journal === null || typeof journal !== "object" ||
    Object.keys(journal).sort().join("\0") !== JOURNAL_KEYS.join("\0") ||
    journal.schemaVersion !== "task-17-mutation-owner-v1" ||
    typeof journal.token !== "string" ||
    typeof journal.workspaceRoot !== "string" ||
    typeof journal.projectRoot !== "string" ||
    typeof journal.quarantineRoot !== "string" ||
    typeof journal.sandboxRoot !== "string" ||
    typeof journal.stagingRoot !== "string" ||
    typeof journal.markerSha256 !== "string" ||
    !new RegExp(`^${UUID}$`, "u").test(journal.token)
  ) return false;
  const sandboxName = path.basename(journal.sandboxRoot);
  const stagingName = path.basename(journal.stagingRoot);
  const marker = markerFor(journal.token, journal.sandboxRoot, journal.stagingRoot);
  return path.resolve(journalPath) === path.resolve(ownerPath(quarantineRoot, journal.token)) &&
    path.resolve(journal.workspaceRoot) === path.resolve(workspaceRoot) &&
    path.resolve(journal.projectRoot) === path.resolve(projectRoot) &&
    path.resolve(journal.quarantineRoot) === path.resolve(quarantineRoot) &&
    path.dirname(path.resolve(journal.sandboxRoot)) === path.resolve(workspaceRoot) &&
    NAME.test(sandboxName) &&
    path.dirname(path.resolve(journal.stagingRoot)) === path.resolve(quarantineRoot) &&
    STAGING_NAME.test(stagingName) &&
    journal.markerSha256 === sha256(markerBytes(marker));
}

function validMarkerShape(marker) {
  return marker !== null &&
    typeof marker === "object" &&
    Object.keys(marker).sort().join("\0") === MARKER_KEYS.join("\0") &&
    marker.schemaVersion === "task-17-mutation-marker-v3" &&
    typeof marker.token === "string" &&
    new RegExp(`^${UUID}$`, "u").test(marker.token) &&
    typeof marker.containerName === "string" &&
    NAME.test(marker.containerName) &&
    typeof marker.stagingName === "string" &&
    STAGING_NAME.test(marker.stagingName);
}

function markerMatchesJournal(marker, journal) {
  if (!validMarkerShape(marker)) return false;
  const expected = markerFor(journal.token, journal.sandboxRoot, journal.stagingRoot);
  return JSON.stringify(marker) === JSON.stringify(expected) &&
    journal.markerSha256 === sha256(markerBytes(marker));
}

function markerFor(token, sandboxRoot, stagingRoot) {
  return {
    schemaVersion: "task-17-mutation-marker-v3",
    token,
    containerName: path.basename(sandboxRoot),
    stagingName: path.basename(stagingRoot)
  };
}

function markerBytes(marker) {
  return `${JSON.stringify(marker)}\n`;
}

function ownerPath(quarantineRoot, token) {
  return path.join(quarantineRoot, `.task17-owner-${token}.json`);
}

async function ensureContainedDirectory(candidate, workspaceRoot) {
  if (!isContainedOrEqual(workspaceRoot, candidate)) {
    throw new TypeError("MUTATION_SANDBOX_PATH_CONTAINMENT_INVALID");
  }
  await assertExistingChain(workspaceRoot, candidate);
  await mkdir(candidate, { recursive: true });
  await assertContainedDirectory(candidate, workspaceRoot);
}

async function assertContainedDirectory(candidate, workspaceRoot) {
  if (!isContainedOrEqual(workspaceRoot, candidate)) {
    throw new TypeError("MUTATION_SANDBOX_PATH_CONTAINMENT_INVALID");
  }
  const relative = path.relative(path.resolve(workspaceRoot), path.resolve(candidate));
  let current = path.resolve(workspaceRoot);
  await assertSafeDirectory(current);
  for (const segment of relative.split(path.sep).filter(Boolean)) {
    current = path.join(current, segment);
    await assertSafeDirectory(current);
  }
}

async function assertExistingChain(workspaceRoot, candidate) {
  const relative = path.relative(path.resolve(workspaceRoot), path.resolve(candidate));
  let current = path.resolve(workspaceRoot);
  await assertSafeDirectory(current);
  for (const segment of relative.split(path.sep).filter(Boolean)) {
    current = path.join(current, segment);
    try {
      await assertSafeDirectory(current);
    } catch (error) {
      if (error instanceof Error && "code" in error && error.code === "ENOENT") return;
      throw error;
    }
  }
}

async function assertSafeDirectory(candidate) {
  const stats = await lstat(candidate);
  if (!stats.isDirectory() || stats.isSymbolicLink()) {
    throw new TypeError("MUTATION_SANDBOX_REPARSE_POINT");
  }
  if (caseInsensitive(await realpath(candidate)) !== caseInsensitive(path.resolve(candidate))) {
    throw new TypeError("MUTATION_SANDBOX_REALPATH_MISMATCH");
  }
}

async function isSafeDirectory(candidate) {
  try {
    await assertSafeDirectory(candidate);
    return true;
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return false;
    }
    throw error;
  }
}

async function assertNoReparsePoints(root) {
  const stats = await lstat(root);
  if (stats.isSymbolicLink()) throw new TypeError("MUTATION_SANDBOX_REPARSE_POINT");
  if (!stats.isDirectory()) return;
  for (const entry of await readdir(root)) {
    await assertNoReparsePoints(path.join(root, entry));
  }
}

function isContainedOrEqual(root, candidate) {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

function caseInsensitive(value) {
  return value.toLowerCase();
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}
