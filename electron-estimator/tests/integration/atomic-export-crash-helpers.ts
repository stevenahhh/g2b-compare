import { spawn } from "node:child_process";
import { once } from "node:events";
import { join } from "node:path";

export async function killBetweenRenames(
  destinationDirectory: string,
  journalRoot: string
): Promise<void> {
  const child = spawn(
    process.env["BUN_BINARY"] ?? "bun",
    [
      "run",
      join(import.meta.dirname, "atomic-export-kill-child.ts"),
      destinationDirectory,
      journalRoot
    ],
    { stdio: ["ignore", "pipe", "pipe"] }
  );
  child.stdout.setEncoding("utf8");
  let stdout = "";
  const ready = new Promise<void>((resolveReady, rejectReady) => {
    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
      if (stdout.includes("READY\n")) {
        resolveReady();
      }
    });
    child.once("error", rejectReady);
    child.once("exit", (code) => {
      if (!stdout.includes("READY\n")) {
        rejectReady(new TypeError(`child exited before READY: ${code}`));
      }
    });
  });
  const timeout = AbortSignal.timeout(30_000);
  await Promise.race([
    ready,
    once(timeout, "abort").then(() => {
      throw new TypeError("kill child timeout");
    })
  ]);
  if (!child.kill()) {
    throw new TypeError("kill child failed");
  }
  await once(child, "exit");
}
