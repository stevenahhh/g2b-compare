import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { expect, test } from "vitest";

test("Given a stale build file When build inventory is asserted Then the stale file is rejected", async () => {
  const root = process.cwd();
  const staleFile = resolve(root, "dist/main/.toolchain-test-stale.js");
  await writeFile(staleFile, "stale\n", "utf8");
  try {
    const result = spawnSync(process.execPath, ["scripts/assert-build.mjs"], { cwd: root, encoding: "utf8" });
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("BUILD_INVENTORY_MISMATCH");
  } finally {
    await rm(staleFile, { force: true });
  }
});

test("Given a stale build file When the build runs Then the stale file is removed", async () => {
  const root = process.cwd();
  const staleFile = resolve(root, "dist/main/.toolchain-build-stale.js");
  await writeFile(staleFile, "stale\n", "utf8");
  const npmCli = process.env.npm_execpath;
  expect(npmCli).toBeDefined();
  const result = spawnSync(process.execPath, [npmCli ?? "", "run", "build"], { cwd: root, encoding: "utf8" });
  expect(result.status).toBe(0);
  const inventory = spawnSync(process.execPath, ["scripts/assert-build.mjs"], { cwd: root, encoding: "utf8" });
  expect(inventory.status).toBe(0);
});

test("Given a bounded evidence command When it exceeds its timeout Then the runner records exit 124", async () => {
  const evidenceDir = await mkdtemp(resolve(tmpdir(), "electron-estimator-evidence-"));
  const descendantPidFile = resolve(evidenceDir, "descendant.pid");
  const unrelated = spawn(
    process.execPath,
    ["-e", "setInterval(() => undefined, 1000)"],
    { stdio: "ignore" }
  );
  const unrelatedPid = unrelated.pid;
  if (unrelatedPid === undefined) {
    throw new TypeError("UNRELATED_PROCESS_PID_MISSING");
  }
  try {
    const nestedProgram = [
      "const{spawn}=require('node:child_process');",
      "const{writeFileSync}=require('node:fs');",
      "const child=spawn(process.execPath,['-e','setInterval(()=>undefined,1000)'],{stdio:'ignore'});",
      "writeFileSync(process.env.TREE_PID_FILE,String(child.pid));",
      "setInterval(()=>undefined,1000);"
    ].join("");
    const result = spawnSync(process.execPath, ["scripts/evidence.mjs", "--name", "timeout-probe", "--timeout-ms", "250", "--", process.execPath, "-e", nestedProgram], {
      cwd: process.cwd(),
      encoding: "utf8",
      env: {
        ...process.env,
        EVIDENCE_DIR: evidenceDir,
        TREE_PID_FILE: descendantPidFile
      }
    });
    expect(result.status).toBe(124);
    const record = JSON.parse(await readFile(resolve(evidenceDir, "timeout-probe.json"), "utf8"));
    const descendantPid = Number(await readFile(descendantPidFile, "utf8"));
    expect(record.exitCode).toBe(124);
    expect(record.timedOut).toBe(true);
    expect(record.processTree.descendantPids).toContain(descendantPid);
    expect(record.processTree.remainingPids).toEqual([]);
    expect(processAlive(descendantPid)).toBe(false);
    expect(processAlive(unrelatedPid)).toBe(true);
  } finally {
    unrelated.kill();
    await rm(evidenceDir, { force: true, recursive: true });
  }
});

function processAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
