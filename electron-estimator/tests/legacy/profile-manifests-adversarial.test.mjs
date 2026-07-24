import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import JSZip from "jszip";

const root = resolve(import.meta.dirname, "../..");
const dataset = resolve(root, "../dataset");
const manifestDir = resolve(root, "resources/manifests/legacy");
const script = resolve(root, "scripts/build-legacy-profiles.mjs");
const files = [
  "gwangyang-direct-2025.json",
  "suncheon-procurement-2025.json",
  "gwangyang-procurement-final-2025.json"
];

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function canonical(value) {
  if (Array.isArray(value)) {
    return value.map(canonical);
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  }
  return value;
}

function manifestDigest(manifest) {
  return sha256(JSON.stringify(canonical(manifest)));
}

async function fixture() {
  const scratch = await mkdtemp(resolve(root, ".legacy-adversarial-"));
  const datasetScratch = await mkdtemp(resolve(tmpdir(), "legacy-dataset-"));
  const copiedScript = resolve(scratch, "scripts/build-legacy-profiles.mjs");
  const copiedManifests = resolve(scratch, "resources/manifests/legacy");
  const copiedDataset = resolve(datasetScratch, "dataset");
  await mkdir(resolve(scratch, "scripts"), { recursive: true });
  await mkdir(copiedManifests, { recursive: true });
  await mkdir(copiedDataset, { recursive: true });
  await cp(script, copiedScript);
  await cp(manifestDir, copiedManifests, { recursive: true });
  for (const file of files) {
    const manifest = JSON.parse(await readFile(resolve(manifestDir, file), "utf8"));
    await cp(resolve(dataset, manifest.source.filename), resolve(copiedDataset, manifest.source.filename));
  }
  return { scratch, datasetScratch, copiedScript, copiedManifests, copiedDataset };
}

async function cleanup(fx) {
  await rm(fx.scratch, { recursive: true, force: true });
  await rm(fx.datasetScratch, { recursive: true, force: true });
}

async function mutateManifest(fx, file, mutate, repin = true) {
  const path = resolve(fx.copiedManifests, file);
  const before = JSON.parse(await readFile(path, "utf8"));
  const after = structuredClone(before);
  mutate(after);
  await writeFile(path, `${JSON.stringify(after, null, 2)}\n`, "utf8");
  if (repin) {
    const verifier = await readFile(fx.copiedScript, "utf8");
    await writeFile(
      fx.copiedScript,
      verifier.replace(manifestDigest(before), manifestDigest(after)),
      "utf8"
    );
  }
  return { before, after };
}

function run(fx) {
  return spawnSync(process.execPath, [fx.copiedScript, "--verify-only", fx.copiedDataset], {
    cwd: root,
    encoding: "utf8"
  });
}

function rejects(result, pattern) {
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, pattern);
}

test("Given capacity is repinned to 999 When verification runs Then semantic validation rejects it", async () => {
  const fx = await fixture();
  try {
    await mutateManifest(fx, files[0], (manifest) => {
      manifest.capacity.rows = 999;
    });
    rejects(run(fx), /LEGACY_PROFILE_SEMANTIC_MISMATCH A capacity/);
  } finally {
    await cleanup(fx);
  }
});

test("Given ownership is repinned bogus and empty When verification runs Then semantic validation rejects it", async () => {
  const fx = await fixture();
  try {
    await mutateManifest(fx, files[1], (manifest) => {
      manifest.ownership.MODEL_INPUT = [];
      manifest.ownership.BOGUS = ["A1"];
      manifest.appOwnedCells = [];
    });
    rejects(run(fx), /LEGACY_PROFILE_SEMANTIC_MISMATCH B ownership/);
  } finally {
    await cleanup(fx);
  }
});

test("Given C U13 to U17 is repinned as a canonical override When verification runs Then warning disposition rejects it", async () => {
  const fx = await fixture();
  try {
    await mutateManifest(fx, files[2], (manifest) => {
      manifest.ownership.CANONICAL_OVERRIDE_FORMULA = ["관급내역서!U13:U17"];
    });
    rejects(run(fx), /LEGACY_PROFILE_SEMANTIC_MISMATCH C warningDisposition/);
  } finally {
    await cleanup(fx);
  }
});

test("Given a pinned filename traverses to the dataset parent When verification runs Then containment rejects it", async () => {
  const fx = await fixture();
  try {
    const manifest = JSON.parse(await readFile(resolve(fx.copiedManifests, files[0]), "utf8"));
    await cp(
      resolve(fx.copiedDataset, manifest.source.filename),
      resolve(fx.datasetScratch, manifest.source.filename)
    );
    await mutateManifest(fx, files[0], (changed) => {
      changed.source.filename = `../${manifest.source.filename}`;
    }, false);
    rejects(run(fx), /LEGACY_SOURCE_PATH_INVALID A/);
  } finally {
    await cleanup(fx);
  }
});

test("Given the formula fingerprint is repinned to zeros When verification runs Then semantic validation rejects it", async () => {
  const fx = await fixture();
  try {
    await mutateManifest(fx, files[0], (manifest) => {
      manifest.activeFormula.combinedFingerprint = "0".repeat(64);
    });
    rejects(run(fx), /LEGACY_PROFILE_SEMANTIC_MISMATCH A activeFormula/);
  } finally {
    await cleanup(fx);
  }
});

test("Given an active source formula changes with source pins updated When verification runs Then recomputed fingerprint rejects it", async () => {
  const fx = await fixture();
  try {
    const path = resolve(fx.copiedManifests, files[0]);
    const manifest = JSON.parse(await readFile(path, "utf8"));
    const sourcePath = resolve(fx.copiedDataset, manifest.source.filename);
    const zip = await JSZip.loadAsync(await readFile(sourcePath));
    const part = "xl/worksheets/sheet2.xml";
    const xml = await zip.file(part).async("text");
    const changedXml = xml.replace(/(<f(?:\s[^>]*)?>)([^<]+)(<\/f>)/, "$1$2+0$3");
    assert.notEqual(changedXml, xml);
    zip.file(part, changedXml, { createFolders: false });
    for (const [name, entry] of Object.entries(zip.files)) {
      if (entry.dir) zip.remove(name);
    }
    const changedBytes = await zip.generateAsync({ type: "nodebuffer" });
    const changedSha = sha256(changedBytes);
    await writeFile(sourcePath, changedBytes);
    const { before, after } = await mutateManifest(fx, files[0], (changed) => {
      changed.source.sha256 = changedSha;
    }, false);
    let verifier = await readFile(fx.copiedScript, "utf8");
    verifier = verifier
      .replaceAll(before.source.sha256, changedSha)
      .replace(manifestDigest(before), manifestDigest(after));
    await writeFile(fx.copiedScript, verifier, "utf8");
    rejects(run(fx), /LEGACY_ACTIVE_FORMULA_MISMATCH A/);
  } finally {
    await cleanup(fx);
  }
});
