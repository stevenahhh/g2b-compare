import assert from "node:assert/strict";
import {
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rename,
  rm,
  symlink,
  unlink,
  writeFile
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import {
  createSandboxChildEnvironment,
  createOwnedSandbox,
  parseMutationProofArguments,
  populateOwnedSandbox,
  recoverOwnedSandboxes,
  removeOwnedSandbox,
  snapshotProductionSurface
} from "../../scripts/mutation-sandbox.mjs";

test("Given mutation proof CLI arguments When parsed Then only target-fixed commands are accepted", () => {
  assert.deepEqual(
    parseMutationProofArguments(["--target", "source-overwrite"]),
    {
      targetName: "source-overwrite",
      npmArgs: [
        "run",
        "test:integration",
        "--",
        "--run",
        "tests/integration/atomic-export.test.ts"
      ]
    }
  );
  assert.deepEqual(
    parseMutationProofArguments(["--target", "validation-fallback"]),
    {
      targetName: "validation-fallback",
      npmArgs: [
        "run",
        "test:integration",
        "--",
        "--run",
        "tests/integration/validation-report-negative.test.ts"
      ]
    }
  );
  for (const attack of [
    ["--target", "source-overwrite", "--", "node", "-e", "process.exit(0)"],
    ["--target", "source-overwrite", "--extra"],
    ["source-overwrite", "--target"],
    ["--target", "unknown"]
  ]) {
    assert.throws(
      () => parseMutationProofArguments(attack),
      /MUTATION_PROOF_ARGUMENTS_INVALID/
    );
  }
});

test("Given an owned sandbox When normal cleanup runs Then only that sandbox is removed", async () => {
  const workspace = await mkdtemp(
    path.join(tmpdir(), "mutation-sandbox-workspace-")
  );
  const project = path.join(workspace, "electron-estimator");
  const quarantine = path.join(workspace, "quarantine");
  await mkdir(project);
  try {
    const created = await createOwnedSandbox(
      workspace,
      project,
      quarantine
    );
    const marker = JSON.parse(
      await readFile(
        path.join(created.sandboxRoot, ".task17-mutation-sandbox.json"),
        "utf8"
      )
    );
    assert.equal(path.dirname(created.sandboxRoot), workspace);
    assert.match(
      path.basename(created.sandboxRoot),
      /^\.electron-estimator-task17-mutation-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u
    );
    assert.deepEqual(
      Object.keys(marker).sort(),
      [
        "containerName",
        "schemaVersion",
        "stagingName",
        "token",
      ]
    );
    assert.equal(marker.schemaVersion, "task-17-mutation-marker-v3");
    assert.equal(
      JSON.stringify(marker).includes(workspace) ||
        JSON.stringify(marker).includes(project),
      false
    );
    assert.equal(
      (await readdir(quarantine)).filter((name) =>
        /^\.task17-owner-[0-9a-f-]{36}\.json$/u.test(name)
      ).length,
      1
    );
    await writeFile(path.join(created.sandboxRoot, "payload"), "test\n");

    await removeOwnedSandbox(
      created.sandboxRoot,
      workspace,
      project,
      created.token,
      quarantine
    );

    await assert.rejects(lstat(created.sandboxRoot), { code: "ENOENT" });
    assert.equal(
      (await readdir(quarantine)).filter((name) =>
        name.startsWith(".task17-owner-")
      ).length,
      0
    );
  } finally {
    await rm(workspace, { recursive: true, force: true });
  }
});

test("Given owned interruption residue and an unowned lookalike When recovery runs Then only owned residue is quarantined", async () => {
  const workspace = await mkdtemp(
    path.join(tmpdir(), "mutation-sandbox-workspace-")
  );
  const project = path.join(workspace, "electron-estimator");
  const quarantine = path.join(workspace, "quarantine");
  await mkdir(project);
  const lookalike = path.join(
    workspace,
    ".electron-estimator-task17-mutation-00000000-0000-0000-0000-000000000000"
  );
  await mkdir(lookalike);
  await writeFile(
    path.join(lookalike, ".task17-mutation-sandbox.json"),
    "{}\n"
  );
  try {
    const created = await createOwnedSandbox(
      workspace,
      project,
      quarantine
    );

    const recovered = await recoverOwnedSandboxes(
      workspace,
      project,
      quarantine
    );

    assert.equal(recovered.length, 1);
    assert.equal(
      JSON.parse(
        await readFile(
          path.join(
            recovered[0],
            ".task17-mutation-sandbox.json"
          ),
          "utf8"
        )
      ).containerName,
      path.basename(created.sandboxRoot)
    );
    assert.equal((await lstat(lookalike)).isDirectory(), true);
    assert.equal(
      (await readdir(workspace)).includes(path.basename(created.sandboxRoot)),
      false
    );
  } finally {
    await rm(workspace, { recursive: true, force: true });
  }
});

test("Given a marker with an extra field When recovery runs Then exact-schema ownership is rejected", async () => {
  const workspace = await mkdtemp(
    path.join(tmpdir(), "mutation-sandbox-workspace-")
  );
  const project = path.join(workspace, "electron-estimator");
  const quarantine = path.join(workspace, "quarantine");
  await mkdir(project);
  try {
    const created = await createOwnedSandbox(workspace, project, quarantine);
    const markerPath = path.join(
      created.sandboxRoot,
      ".task17-mutation-sandbox.json"
    );
    const marker = JSON.parse(await readFile(markerPath, "utf8"));
    await writeFile(
      markerPath,
      `${JSON.stringify({ ...marker, untrusted: true })}\n`
    );

    await assert.rejects(
      removeOwnedSandbox(
        created.sandboxRoot,
        workspace,
        project,
        created.token,
        quarantine
      ),
      /MUTATION_SANDBOX_OWNERSHIP_INVALID/
    );
    const recovered = await recoverOwnedSandboxes(
      workspace,
      project,
      quarantine
    );

    assert.equal(recovered.length, 0);
    assert.equal((await lstat(created.sandboxRoot)).isDirectory(), true);
  } finally {
    await rm(workspace, { recursive: true, force: true });
  }
});

test("Given owned staging interruption residue When recovery runs Then the staging directory is quarantined", async () => {
  const workspace = await mkdtemp(
    path.join(tmpdir(), "mutation-sandbox-workspace-")
  );
  const project = path.join(workspace, "electron-estimator");
  const quarantine = path.join(workspace, "quarantine");
  await mkdir(project);
  try {
    const created = await createOwnedSandbox(workspace, project, quarantine);
    const markerPath = path.join(
      created.sandboxRoot,
      ".task17-mutation-sandbox.json"
    );
    const marker = JSON.parse(await readFile(markerPath, "utf8"));
    const stagingRoot = path.join(quarantine, marker.stagingName);
    await unlink(markerPath);
    await rename(created.sandboxRoot, stagingRoot);

    const recovered = await recoverOwnedSandboxes(
      workspace,
      project,
      quarantine
    );

    assert.equal(recovered.length, 1);
    await assert.rejects(lstat(stagingRoot), { code: "ENOENT" });
    assert.match(path.basename(recovered[0]), /^stale-staging-/u);
  } finally {
    await rm(workspace, { recursive: true, force: true });
  }
});

test("Given project dependencies and sibling dataset When sandbox is populated Then every input is a private container copy", async () => {
  const workspace = await mkdtemp(
    path.join(tmpdir(), "mutation-sandbox-workspace-")
  );
  const project = path.join(workspace, "electron-estimator");
  const dataset = path.join(workspace, "dataset");
  const quarantine = path.join(workspace, "quarantine");
  await mkdir(path.join(project, "node_modules", "example"), {
    recursive: true
  });
  for (const directory of ["dist", "release", "test-results"]) {
    await mkdir(path.join(project, directory), { recursive: true });
    await writeFile(
      path.join(project, directory, "artifact.txt"),
      `${directory}\n`
    );
  }
  await mkdir(dataset);
  await writeFile(path.join(project, "source.ts"), "original\n");
  await writeFile(
    path.join(project, "node_modules", "example", "index.js"),
    "dependency\n"
  );
  await writeFile(path.join(dataset, "workbook.xlsx"), "dataset\n");
  try {
    const created = await createOwnedSandbox(
      workspace,
      project,
      quarantine
    );
    const populated = await populateOwnedSandbox(
      created.sandboxRoot,
      project,
      dataset,
      quarantine
    );

    assert.equal(
      populated.sandboxProjectRoot,
      path.join(created.sandboxRoot, "electron-estimator")
    );
    assert.equal(
      populated.sandboxDatasetRoot,
      path.join(created.sandboxRoot, "dataset")
    );
    assert.equal(populated.reparsePointCount, 0);
    assert.equal(
      (await lstat(
        path.join(populated.sandboxProjectRoot, "node_modules")
      )).isSymbolicLink(),
      false
    );
    for (const directory of ["dist", "release", "test-results"]) {
      assert.equal(
        await readFile(
          path.join(
            populated.sandboxProjectRoot,
            directory,
            "artifact.txt"
          ),
          "utf8"
        ),
        `${directory}\n`
      );
    }
    await writeFile(
      path.join(populated.sandboxProjectRoot, "source.ts"),
      "sandbox\n"
    );
    await writeFile(
      path.join(populated.sandboxDatasetRoot, "workbook.xlsx"),
      "sandbox dataset\n"
    );
    assert.equal(await readFile(path.join(project, "source.ts"), "utf8"), "original\n");
    assert.equal(
      await readFile(path.join(dataset, "workbook.xlsx"), "utf8"),
      "dataset\n"
    );
    await removeOwnedSandbox(
      created.sandboxRoot,
      workspace,
      project,
      created.token,
      quarantine
    );
  } finally {
    await rm(workspace, { recursive: true, force: true });
  }
});

test("Given hostile inherited variables When child environment is created Then only fixed private values are used", async () => {
  const workspace = await mkdtemp(
    path.join(tmpdir(), "mutation-sandbox-workspace-")
  );
  const sandboxRoot = path.join(workspace, "container");
  const sandboxProjectRoot = path.join(
    sandboxRoot,
    "electron-estimator"
  );
  const binaryRoot = path.join(
    sandboxProjectRoot,
    "node_modules",
    ".bin"
  );
  await mkdir(binaryRoot, { recursive: true });
  const injected = {
    NODE_OPTIONS: "--require=C:\\attack\\hook.js",
    NODE_PATH: "C:\\attack\\modules",
    INIT_CWD: "C:\\attack",
    npm_execpath: "C:\\attack\\npm-cli.js",
    COMSPEC: "C:\\attack\\cmd.exe",
    PATH: "C:\\attack\\bin",
    SYSTEMROOT: "C:\\attack\\windows",
    WINDIR: "C:\\attack\\windows",
    PATHEXT: ".ATTACK",
    TEMP: "C:\\attack\\temp",
    TMP: "C:\\attack\\tmp",
    HOME: "C:\\attack\\home",
    USERPROFILE: "C:\\attack\\profile"
  };
  const previous = Object.fromEntries(
    Object.keys(injected).map((key) => [key, process.env[key]])
  );
  Object.assign(process.env, injected);
  try {
    const environment = await createSandboxChildEnvironment({
      sandboxRoot,
      sandboxProjectRoot,
      nodeRuntime: process.execPath
    });
    const canonicalRuntime = await realpath(process.execPath);
    const runtimeRoot = await realpath(path.dirname(canonicalRuntime));
    const windowsRoot = await realpath(
      path.join(path.parse(canonicalRuntime).root, "Windows")
    );
    const system32 = await realpath(path.join(windowsRoot, "System32"));

    assert.deepEqual(
      Object.keys(environment).sort(),
      [
        "COMSPEC",
        "HOME",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR"
      ]
    );
    for (const key of ["NODE_OPTIONS", "NODE_PATH", "INIT_CWD", "npm_execpath"]) {
      assert.equal(environment[key], undefined);
    }
    assert.equal(
      Object.values(environment).some((value) => value.includes("C:\\attack")),
      false
    );
    assert.equal(
      environment.PATH,
      [
        await realpath(binaryRoot),
        runtimeRoot,
        system32
      ].join(path.delimiter)
    );
    assert.equal(environment.COMSPEC, await realpath(path.join(system32, "cmd.exe")));
    assert.equal(environment.SYSTEMROOT, windowsRoot);
    assert.equal(environment.WINDIR, windowsRoot);
    assert.equal(environment.PATHEXT, ".COM;.EXE;.BAT;.CMD");
    assert.equal(environment.TEMP, environment.TMP);
    assert.equal(environment.HOME, environment.USERPROFILE);
    assert.equal(
      path.dirname(environment.TEMP),
      path.join(sandboxRoot, ".child-env")
    );
    assert.equal(
      path.dirname(environment.HOME),
      path.join(sandboxRoot, ".child-env")
    );
    assert.equal((await lstat(environment.TEMP)).isDirectory(), true);
    assert.equal((await lstat(environment.HOME)).isDirectory(), true);
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(workspace, { recursive: true, force: true });
  }
});

test("Given production project and dataset When either surface changes Then the manifest digest changes", async () => {
  const workspace = await mkdtemp(
    path.join(tmpdir(), "mutation-sandbox-workspace-")
  );
  const project = path.join(workspace, "electron-estimator");
  const dataset = path.join(workspace, "dataset");
  await mkdir(project);
  await mkdir(dataset);
  await writeFile(path.join(project, "source.ts"), "original\n");
  await writeFile(path.join(dataset, "workbook.xlsx"), "dataset\n");
  try {
    const before = await snapshotProductionSurface(project, dataset);
    await writeFile(path.join(dataset, "workbook.xlsx"), "changed\n");
    const after = await snapshotProductionSurface(project, dataset);

    assert.notEqual(after.digest, before.digest);
    assert.equal(before.fileCount, 2);
  } finally {
    await rm(workspace, { recursive: true, force: true });
  }
});

test("Given a generated project output When production is snapshotted Then the output is part of the immutable manifest", async () => {
  const workspace = await mkdtemp(
    path.join(tmpdir(), "mutation-sandbox-workspace-")
  );
  const generated = path.join(
    workspace,
    "electron-estimator",
    "dist",
    "main.js"
  );
  await mkdir(path.dirname(generated), { recursive: true });
  await mkdir(path.join(workspace, "dataset"));
  await writeFile(generated, "before\n");
  try {
    const before = await snapshotProductionSurface(
      path.join(workspace, "electron-estimator"),
      path.join(workspace, "dataset")
    );
    await writeFile(generated, "after\n");
    const after = await snapshotProductionSurface(
      path.join(workspace, "electron-estimator"),
      path.join(workspace, "dataset")
    );

    assert.notEqual(after.digest, before.digest);
    assert.equal(after.fileCount, before.fileCount);
  } finally {
    await rm(workspace, { recursive: true, force: true });
  }
});

test("Given a forged exact marker without an owner journal When recovery runs Then the lookalike is untouched", async () => {
  const workspace = await mkdtemp(
    path.join(tmpdir(), "mutation-sandbox-workspace-")
  );
  const project = path.join(workspace, "electron-estimator");
  const quarantine = path.join(workspace, "quarantine");
  const containerName =
    ".electron-estimator-task17-mutation-10000000-0000-4000-8000-000000000000";
  const forged = path.join(workspace, containerName);
  await mkdir(project);
  await mkdir(forged);
  await writeFile(
    path.join(forged, ".task17-mutation-sandbox.json"),
    `${JSON.stringify({
      schemaVersion: "task-17-mutation-marker-v3",
      token: "30000000-0000-4000-8000-000000000000",
      containerName,
      stagingName: ".staging-20000000-0000-4000-8000-000000000000"
    })}\n`
  );
  try {
    const recovered = await recoverOwnedSandboxes(
      workspace,
      project,
      quarantine
    );

    assert.equal(recovered.length, 0);
    assert.equal((await lstat(forged)).isDirectory(), true);
  } finally {
    await rm(workspace, { recursive: true, force: true });
  }
});

test("Given the project root is a junction When population starts Then source containment is rejected", async () => {
  const workspace = await mkdtemp(
    path.join(tmpdir(), "mutation-sandbox-workspace-")
  );
  const outside = await mkdtemp(
    path.join(tmpdir(), "mutation-sandbox-outside-")
  );
  const project = path.join(workspace, "electron-estimator");
  const dataset = path.join(workspace, "dataset");
  const quarantine = path.join(workspace, "quarantine");
  await mkdir(path.join(outside, "node_modules"), { recursive: true });
  await mkdir(dataset);
  await symlink(outside, project, "junction");
  try {
    await assert.rejects(
      createOwnedSandbox(
        workspace,
        project,
        quarantine
      ),
      /MUTATION_SANDBOX_REPARSE_POINT/
    );
  } finally {
    await rm(workspace, { recursive: true, force: true });
    await rm(outside, { recursive: true, force: true });
  }
});

test("Given the owner journal root is a junction When sandbox creation starts Then no external control file is written", async () => {
  const workspace = await mkdtemp(
    path.join(tmpdir(), "mutation-sandbox-workspace-")
  );
  const outside = await mkdtemp(
    path.join(tmpdir(), "mutation-sandbox-outside-")
  );
  const project = path.join(workspace, "electron-estimator");
  const quarantine = path.join(workspace, "quarantine");
  await mkdir(project);
  await symlink(outside, quarantine, "junction");
  try {
    await assert.rejects(
      createOwnedSandbox(workspace, project, quarantine),
      /MUTATION_SANDBOX_REPARSE_POINT/
    );
    assert.deepEqual(await readdir(outside), []);
  } finally {
    await rm(workspace, { recursive: true, force: true });
    await rm(outside, { recursive: true, force: true });
  }
});
