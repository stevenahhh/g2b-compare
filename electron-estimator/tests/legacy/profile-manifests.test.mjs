import { execFileSync, spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { once } from "node:events";
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, resolve } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

const root = resolve(import.meta.dirname, "../..");
const dataset = resolve(root, "../dataset");
const manifestDir = resolve(root, "resources/manifests/legacy");
const script = resolve(root, "scripts/build-legacy-profiles.mjs");
const expected = [
  {
    file: "gwangyang-direct-2025.json",
    id: "A",
    sha256: "445012e259ab5318a1d52468cce93ee28a55a8bcb467876f40a47a939e4668db",
    sheets: 6,
    activeCells: 85,
    capacity: 16,
    total: 39149530,
    fingerprint: "12c6350721319f61a5d3415f9c549c33458a09ec3c2021c25b846518687fb894"
  },
  {
    file: "suncheon-procurement-2025.json",
    id: "B",
    sha256: "2220cd9936ebdf908d64c0571a4c8de83973eaa89c6778a64afec07de7c5e701",
    sheets: 20,
    activeCells: 318,
    capacity: 9,
    total: 20284000,
    fingerprint: "fbc75ff96ab44d24867b16f5d6fa1c09f5964b1539b9d5c8cb5c8b2e501fe568"
  },
  {
    file: "gwangyang-procurement-final-2025.json",
    id: "C",
    sha256: "8a55700bdaf62a00c208c7286531fd56ca321571f73f7620505a823ef5d4d0f1",
    sheets: 17,
    activeCells: 980,
    capacity: 24,
    total: 65854000,
    fingerprint: "1dd24082c48e03ac8b624df0be4fd26f65ec10afa83da0c2ee389667bd511990"
  }
];

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  }
  return value;
}

function manifestDigest(manifest) {
  return createHash("sha256").update(JSON.stringify(canonical(manifest))).digest("hex");
}

test("Given the pinned profiles When their manifests are read Then exact source and ownership contracts are present", async () => {
  for (const profile of expected) {
    const manifest = JSON.parse(await readFile(resolve(manifestDir, profile.file), "utf8"));
    assert.equal(manifest.schemaVersion, "legacy-workbook-profile-v1");
    assert.equal(manifest.profileId, profile.id);
    assert.equal(manifest.source.sha256, profile.sha256);
    assert.equal(manifest.sheetMap.length, profile.sheets);
    assert.equal(manifest.activeFormula.cellCount, profile.activeCells);
    assert.equal(manifest.capacity.rows, profile.capacity);
    assert.equal(manifest.totalOracle.totalWon, profile.total);
    assert.equal(manifest.activeFormula.combinedFingerprint, profile.fingerprint);
    assert.deepEqual(manifest.ownership.CANONICAL_OVERRIDE_FORMULA, []);
    assert.ok(manifest.appOwnedCells.length > 0);
    assert.ok(manifest.ownership.MODEL_INPUT.length > 0);
    assert.ok(manifest.ownership.VALID_TEMPLATE_FORMULA.length > 0);
    assert.ok(manifest.formulaCacheCells.length > 0);
    assert.deepEqual(manifest.packageDriftAllowlist, [
      "[Content_Types].xml#calcChain-override",
      "xl/_rels/workbook.xml.rels#calcChain-relationship",
      "xl/calcChain.xml",
      "xl/workbook.xml#calcPr"
    ]);
  }
  const c = JSON.parse(
    await readFile(resolve(manifestDir, "gwangyang-procurement-final-2025.json"), "utf8")
  );
  assert.deepEqual(c.inheritedWarnings.originalFormulaCells, [
    "관급내역서!U13=단가조사!F18",
    "관급내역서!U14=단가조사!F19",
    "관급내역서!U15=단가조사!F20",
    "관급내역서!U16=단가조사!F21",
    "관급내역서!U17=단가조사!F22"
  ]);
  const bundled = execFileSync(
    "powershell",
    [
      "-NoProfile",
      "-Command",
      `(Get-ChildItem -LiteralPath '${root.replaceAll("'", "''")}' -Recurse -File -ErrorAction SilentlyContinue | Where-Object Extension -in '.xlsx','.xlsm').Count`
    ],
    { encoding: "utf8" }
  ).trim();
  assert.equal(bundled, "0");
});

test("Given the original dataset When verification runs twice Then the summaries are deterministic", () => {
  const first = execFileSync(process.execPath, [script, "--verify-only", dataset], {
    cwd: root,
    encoding: "utf8"
  });
  const second = execFileSync(process.execPath, [script, "--verify-only", dataset], {
    cwd: root,
    encoding: "utf8"
  });
  assert.equal(first, second);
  const summary = JSON.parse(first);
  assert.equal(summary.status, "PASS");
  assert.deepEqual(
    summary.profiles.map(({ id, capacity, totalWon }) => ({ id, capacity, totalWon })),
    [
      { id: "A", capacity: 16, totalWon: 39149530 },
      { id: "B", capacity: 9, totalWon: 20284000 },
      { id: "C", capacity: 24, totalWon: 65854000 }
    ]
  );
});

test("Given a same-name corrupted source When verification runs Then the hash mismatch is explicit", async () => {
  const scratch = await mkdtemp(resolve(tmpdir(), "legacy-profile-"));
  try {
    for (const profile of expected) {
      const manifest = JSON.parse(await readFile(resolve(manifestDir, profile.file), "utf8"));
      await cp(resolve(dataset, manifest.source.filename), resolve(scratch, manifest.source.filename));
    }
    const bManifest = JSON.parse(
      await readFile(resolve(manifestDir, "suncheon-procurement-2025.json"), "utf8")
    );
    await writeFile(resolve(scratch, bManifest.source.filename), "corrupt-source", "utf8");
    const result = spawnSync(process.execPath, [script, "--verify-only", scratch], {
      cwd: root,
      encoding: "utf8"
    });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /LEGACY_SOURCE_HASH_MISMATCH/);
    assert.ok(result.stderr.includes(basename(bManifest.source.filename)));
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("Given a stale copied inventory When verification runs Then the inventory mismatch is explicit", async () => {
  const scratch = await mkdtemp(resolve(root, ".legacy-stale-"));
  try {
    await mkdir(resolve(scratch, "scripts"), { recursive: true });
    await mkdir(resolve(scratch, "resources/manifests/legacy"), { recursive: true });
    const staleScript = resolve(scratch, "scripts/build-legacy-profiles.mjs");
    await cp(script, staleScript);
    await cp(manifestDir, resolve(scratch, "resources/manifests/legacy"), { recursive: true });
    const stalePath = resolve(scratch, "resources/manifests/legacy/gwangyang-direct-2025.json");
    const stale = JSON.parse(await readFile(stalePath, "utf8"));
    const oldDigest = manifestDigest(stale);
    stale.baselineInventory.externalLinks.count = 1;
    await writeFile(stalePath, `${JSON.stringify(stale)}\n`, "utf8");
    const verifier = await readFile(staleScript, "utf8");
    await writeFile(staleScript, verifier.replace(oldDigest, manifestDigest(stale)), "utf8");
    const result = spawnSync(
      process.execPath,
      [staleScript, "--verify-only", dataset],
      { cwd: root, encoding: "utf8" }
    );
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /LEGACY_PROFILE_INVENTORY_MISMATCH A baselineInventory/);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("Given a malformed dataset path When verification runs Then the path error is explicit", () => {
  const result = spawnSync(process.execPath, [script, "--verify-only", resolve(root, "missing-dataset")], {
    cwd: root,
    encoding: "utf8"
  });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /LEGACY_DATASET_PATH_INVALID/);
});

test("Given a verifier interrupted during startup When it is rerun Then originals still verify", async () => {
  const child = spawn(process.execPath, [script, "--verify-only", dataset], {
    cwd: root,
    windowsHide: true
  });
  assert.equal(child.kill(), true);
  const [code, signal] = await once(child, "exit");
  assert.ok(code !== 0 || signal !== null);
  const rerun = spawnSync(process.execPath, [script, "--verify-only", dataset], {
    cwd: root,
    encoding: "utf8"
  });
  assert.equal(rerun.status, 0);
  assert.equal(JSON.parse(rerun.stdout).status, "PASS");
});
