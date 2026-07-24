import assert from "node:assert/strict";
import {
  mkdir,
  mkdtemp,
  rm,
  writeFile
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { findFilesystemResidue } from "../../scripts/cleanup-audit.mjs";

const fixtureRoots = [];

test.afterEach(async () => {
  await Promise.all(
    fixtureRoots.splice(0).map((root) =>
      rm(root, { recursive: true, force: true })
    )
  );
});

test("Given product-root debug artifacts When cleanup scans Then every artifact is residue", async () => {
  const fixture = await createFixture();
  const expected = [
    path.join(fixture.projectRoot, ".debug-journal.md"),
    path.join(fixture.projectRoot, ".tmp-legacy-import.mjs"),
    path.join(fixture.projectRoot, "$log")
  ];
  await Promise.all(expected.map((file) => writeFile(file, "residue\n")));

  const residue = await findFilesystemResidue(fixture);

  assert.deepEqual(
    residue.filter((file) => expected.includes(file)),
    expected.sort()
  );
});

test("Given staging adjacent and live sandbox artifacts When cleanup scans Then every live path is residue", async () => {
  const fixture = await createFixture();
  const staging = path.join(fixture.matrixRoot, ".staging-fixture");
  const sandbox = path.join(
    fixture.workspaceRoot,
    ".electron-estimator-task17-mutation-20000000-0000-4000-8000-000000000000"
  );
  const backup = path.join(
    fixture.projectRoot,
    "src",
    "legacy",
    "export",
    "paths.ts.task17-fixture.backup"
  );
  const observed = path.join(
    fixture.projectRoot,
    "src",
    "legacy",
    "validation",
    "report.ts.task17-fixture.observed"
  );
  await Promise.all([
    mkdir(staging),
    mkdir(sandbox),
    writeFile(backup, "backup\n"),
    writeFile(observed, "observed\n")
  ]);

  const residue = await findFilesystemResidue(fixture);

  assert.deepEqual(
    residue.filter((file) =>
      [staging, sandbox, backup, observed].includes(file)
    ),
    [staging, sandbox, backup, observed].sort()
  );
});

test("Given retained quarantine artifacts When cleanup scans Then retained evidence is excluded", async () => {
  const fixture = await createFixture();
  const quarantine = path.join(fixture.matrixRoot, "quarantine");
  const staging = path.join(quarantine, ".staging-retained");
  const unrelatedQuarantine = path.join(
    fixture.matrixRoot,
    "stages",
    "quarantine"
  );
  const liveResidue = path.join(unrelatedQuarantine, ".tmp-live");
  await mkdir(staging, { recursive: true });
  await mkdir(unrelatedQuarantine, { recursive: true });
  await writeFile(
    path.join(quarantine, ".debug-journal.md"),
    "retained evidence\n"
  );
  await writeFile(liveResidue, "live residue\n");

  const residue = await findFilesystemResidue(fixture);

  assert.equal(residue.includes(staging), true);
  assert.equal(residue.includes(liveResidue), true);
  assert.equal(
    residue.some(
      (file) => file.startsWith(quarantine) && file !== staging
    ),
    false
  );
});

test("Given sandbox quarantine staging and retained stale artifacts When cleanup scans Then only staging is residue", async () => {
  const fixture = await createFixture();
  const staging = path.join(
    fixture.sandboxQuarantineRoot,
    ".staging-20000000-0000-4000-8000-000000000000"
  );
  const retained = path.join(
    fixture.sandboxQuarantineRoot,
    "stale-.electron-estimator-task17-mutation-retained"
  );
  await Promise.all([mkdir(staging), mkdir(retained)]);

  const residue = await findFilesystemResidue(fixture);

  assert.equal(residue.includes(staging), true);
  assert.equal(residue.includes(retained), false);
});

async function createFixture() {
  const workspaceRoot = await mkdtemp(
    path.join(tmpdir(), "cleanup-audit-contract-")
  );
  fixtureRoots.push(workspaceRoot);
  const projectRoot = path.join(workspaceRoot, "electron-estimator");
  const taskEvidenceRoot = path.join(workspaceRoot, "task-17");
  const matrixRoot = path.join(taskEvidenceRoot, "attempt-fixture");
  const tempRoot = path.join(workspaceRoot, "temp");
  const managedJournalRoot = path.join(tempRoot, "managed-journal");
  const mutationGuardRoot = path.join(tempRoot, "mutation-guard");
  const sandboxQuarantineRoot = path.join(
    taskEvidenceRoot,
    "container-sandbox-fix",
    "quarantine"
  );
  await Promise.all([
    mkdir(path.join(projectRoot, "src", "legacy", "export"), {
      recursive: true
    }),
    mkdir(path.join(projectRoot, "src", "legacy", "validation"), {
      recursive: true
    }),
    mkdir(matrixRoot, { recursive: true }),
    mkdir(tempRoot),
    mkdir(sandboxQuarantineRoot, { recursive: true })
  ]);
  return {
    projectRoot,
    workspaceRoot,
    taskEvidenceRoot,
    matrixRoot,
    tempRoot,
    managedJournalRoot,
    mutationGuardRoot,
    sandboxQuarantineRoot
  };
}
