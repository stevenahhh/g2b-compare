import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { auditRoot } from "../../scripts/assert-no-slop.mjs";

const roots = [];

test.afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

test("Given source and resource slop When audited Then stable violation codes are reported", async () => {
  const root = await fixture();
  await writeFile(path.join(root, "src", "bad.ts"), "// @ts-ignore\nconst value: any = 1;\ntry {} catch {}\n");
  await Promise.all([
    writeFile(path.join(root, "resources", "data", "first.json"), "same\n"),
    writeFile(path.join(root, "resources", "data", "second.json"), "same\n"),
    writeFile(path.join(root, "tsconfig.test.json"), "{}\n")
  ]);

  const result = await auditRoot(root);

  assert.deepEqual(result.violations.map((item) => item.code), [
    "ANY_KEYWORD",
    "DUPLICATE_RESOURCE",
    "EMPTY_CATCH",
    "SPECULATIVE_CONFIG",
    "SUPPRESSIVE_DIRECTIVE"
  ]);
});

test("Given the project root When audited Then every category is clean", async () => {
  const result = await auditRoot(path.resolve(import.meta.dirname, "..", ".."));

  assert.equal(result.status, "pass");
  assert.deepEqual(result.categoryCounts, {
    "any-keyword": 0,
    "duplicate-resource": 0,
    "empty-catch": 0,
    "speculative-config": 0,
    "suppressive-directive": 0
  });
});

async function fixture() {
  const root = await mkdtemp(path.join(tmpdir(), "assert-no-slop-"));
  roots.push(root);
  await Promise.all(["src", "scripts", "tests", "resources/data"].map((directory) =>
    mkdir(path.join(root, directory), { recursive: true })
  ));
  await writeFile(path.join(root, "package.json"), "{\"scripts\":{}}\n");
  return root;
}
