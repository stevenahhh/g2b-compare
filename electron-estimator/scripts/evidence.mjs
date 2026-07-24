import { mkdir, readdir, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { spawn } from "node:child_process";
import {
  captureProcessIdentity,
  terminateOwnedProcessTree
} from "./process-tree.mjs";

const args = process.argv.slice(2);
const nameIndex = args.indexOf("--name");
const separator = args.indexOf("--");
const redGreen = args.includes("--red-green-build");
const timeoutIndex = args.indexOf("--timeout-ms");
if (nameIndex === -1 || separator === -1 || !args[nameIndex + 1] || separator === args.length - 1) {
  throw new Error("Usage: npm run evidence -- --name <name> -- <command> [...args]");
}
const name = args[nameIndex + 1];
if (!/^[a-z0-9][a-z0-9-]*$/i.test(name)) {
  throw new Error("Evidence name must contain only letters, digits, and hyphens.");
}
const timeoutMs = timeoutIndex === -1
  ? name.startsWith("task-17-")
    ? 600_000
    : 30_000
  : Number(args[timeoutIndex + 1]);
if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 600_000) {
  throw new Error("--timeout-ms must be an integer from 1 through 600000.");
}
const command = args[separator + 1];
const commandArgs = args.slice(separator + 2);
const evidenceDir = await resolveEvidenceDirectory(name);
const run = () => new Promise((complete) => {
  const npmCli = process.env.npm_execpath;
  const executable = command === "npm" && npmCli ? process.execPath : command;
  const executableArgs = command === "npm" && npmCli ? [npmCli, ...commandArgs] : commandArgs;
  const child = spawn(executable, executableArgs, {
    cwd: process.cwd(),
    env: { ...process.env, EVIDENCE_DIR: evidenceDir },
    shell: false
  });
  let output = "";
  let timedOut = false;
  let completed = false;
  let termination = Promise.resolve(null);
  const rootIdentity = process.platform === "win32"
    ? captureProcessIdentity(child.pid).catch(() => null)
    : Promise.resolve(null);
  const finish = (result) => {
    if (!completed) {
      completed = true;
      clearTimeout(timer);
      complete(result);
    }
  };
  const timer = setTimeout(() => {
    timedOut = true;
    termination = rootIdentity.then((identity) => {
      if (process.platform === "win32" && identity === null) {
        throw new TypeError("PROCESS_TREE_ROOT_IDENTITY_MISSING");
      }
      return terminateOwnedProcessTree(identity ?? child.pid);
    });
  }, timeoutMs);
  child.stdout.on("data", (chunk) => { output += String(chunk); process.stdout.write(chunk); });
  child.stderr.on("data", (chunk) => { output += String(chunk); process.stderr.write(chunk); });
  child.on("error", (error) => finish({ code: 1, output: `${output}${error.message}\n`, signal: null, timedOut, processTree: null }));
  child.on("close", async (code, signal) => {
    try {
      const processTree = await termination;
      finish({ code: timedOut ? 124 : code, output, signal, timedOut, processTree });
    } catch (error) {
      finish({
        code: 1,
        output: `${output}${error instanceof Error ? error.message : String(error)}\n`,
        signal,
        timedOut,
        processTree: null
      });
    }
  });
});
await mkdir(evidenceDir, { recursive: true });
const writeRecord = async (suffix, result) => {
  const record = { command: [command, ...commandArgs], exitCode: result.code, output: result.output, signal: result.signal, timedOut: result.timedOut, processTree: result.processTree };
  await writeFile(resolve(evidenceDir, `${name}${suffix}.json`), `${JSON.stringify(record, null, 2)}\n`, "utf8");
};
if (redGreen) {
  const staleFile = resolve(process.cwd(), "dist/main/.task-1-stale.js");
  await writeFile(staleFile, "stale\n", "utf8");
  const red = await run();
  await writeRecord("-red", red);
  await rm(staleFile, { force: true });
  const green = await run();
  await writeRecord("-green", green);
  if (red.code === 0 || green.code !== 0) {
    process.exitCode = 1;
  }
} else {
  const result = await run();
  await writeRecord("", result);
  process.exitCode = result.code ?? 1;
}

async function resolveEvidenceDirectory(evidenceName) {
  if (process.env.EVIDENCE_DIR !== undefined) {
    return resolve(process.env.EVIDENCE_DIR);
  }
  const task = evidenceName.match(/^task-(\d+)-/u);
  if (task === null) {
    return resolve(
      process.cwd(),
      "../.omo/evidence/electron-estimator/task-1"
    );
  }
  const taskRoot = resolve(
    process.cwd(),
    `../.omo/evidence/electron-estimator/task-${task[1]}`
  );
  await mkdir(taskRoot, { recursive: true });
  const attempts = (await readdir(taskRoot))
    .map((entry) => /^attempt-(\d{3})$/u.exec(entry))
    .filter((entry) => entry !== null)
    .map((entry) => Number(entry[1]));
  let next = (attempts.length === 0 ? 0 : Math.max(...attempts)) + 1;
  for (;;) {
    const candidate = resolve(
      taskRoot,
      `attempt-${String(next).padStart(3, "0")}`
    );
    try {
      await mkdir(candidate);
      return candidate;
    } catch (error) {
      if (
        !(error instanceof Error) ||
        !("code" in error) ||
        error.code !== "EEXIST"
      ) {
        throw error;
      }
      next += 1;
    }
  }
}
