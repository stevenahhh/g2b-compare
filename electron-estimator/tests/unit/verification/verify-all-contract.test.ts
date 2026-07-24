import { spawn } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { expect, test } from "vitest";
import { z } from "zod";

const StageSchema = z
  .strictObject({
    id: z.string().min(1),
    kind: z.enum(["check", "test", "oracle", "package", "cleanup"])
  })
  .readonly();

const MatrixSchema = z
  .strictObject({
    schemaVersion: z.literal("task-17-verify-matrix-v1"),
    stages: z.array(StageSchema).min(1).readonly()
  })
  .readonly();

test("Given the verification runner When its matrix is listed Then every required gate appears exactly once", async () => {
  // Given / When
  const result = await runNode(["scripts/verify-all.mjs", "--list"]);

  // Then
  expect(result.code).toBe(0);
  const matrix = MatrixSchema.parse(JSON.parse(result.stdout));
  expect(matrix.stages.map((stage) => stage.id)).toEqual([
    "typecheck",
    "build",
    "unit",
    "integration",
    "security",
    "data-contracts-legacy",
    "electron-native-legacy",
    "electron-renderer",
    "package-asar",
    "artifact-oracle",
    "cleanup-audit"
  ]);
});

test("Given a reused evidence root When verification starts Then stale artifacts are rejected before any stage runs", async () => {
  const evidenceRoot = await mkdtemp(
    path.join(tmpdir(), "verify-root-contract-")
  );
  try {
    await writeFile(
      path.join(evidenceRoot, "stale.json"),
      "{}\n",
      "utf8"
    );

    const result = await runNode(["scripts/verify-all.mjs"], {
      ...process.env,
      EVIDENCE_DIR: evidenceRoot
    });

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("VERIFY_EVIDENCE_ROOT_NOT_EMPTY");
    expect(result.stdout).not.toContain("[verify:all]");
  } finally {
    await rm(evidenceRoot, { recursive: true, force: true });
  }
});

function runNode(
  args: readonly string[],
  environment: NodeJS.ProcessEnv = process.env
): Promise<{
  readonly code: number;
  readonly stdout: string;
  readonly stderr: string;
}> {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(process.execPath, args, {
      cwd: process.cwd(),
      env: environment,
      shell: false
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString("utf8");
    });
    child.once("error", rejectPromise);
    child.once("close", (code) => {
      resolvePromise({ code: code ?? 1, stdout, stderr });
    });
  });
}
