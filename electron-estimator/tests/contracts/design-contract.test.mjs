import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { test } from "node:test";
import { pathToFileURL } from "node:url";

const root = resolve(import.meta.dirname, "../..");
const modulePath = resolve(root, "src/renderer/design-contract.ts");
const snapshotPath = resolve(root, "resources/design-contract.snapshot.json");
const docsPath = resolve(root, "DESIGN.md");
const validatorPath = resolve(root, "tests/contracts/assert-design.mjs");
const forbiddenFixturePath = resolve(root, "tests/fixtures/design/forbidden-gradient.json");

async function loadContract() {
  const { DESIGN_CONTRACT } = await import(pathToFileURL(modulePath).href);
  return DESIGN_CONTRACT;
}

function collectStringValues(value, output = []) {
  if (typeof value === "string") {
    output.push(value);
    return output;
  }
  if (Array.isArray(value)) {
    for (const item of value) collectStringValues(item, output);
    return output;
  }
  if (value !== null && typeof value === "object") {
    for (const item of Object.values(value)) collectStringValues(item, output);
  }
  return output;
}

test("Concept A module and generated snapshot are complete and equal", async () => {
  assert.equal(existsSync(modulePath), true, "design contract module must exist");
  assert.equal(existsSync(snapshotPath), true, "design contract snapshot must exist");

  const contract = await loadContract();
  const snapshot = JSON.parse(readFileSync(snapshotPath, "utf8"));

  assert.deepEqual(contract, snapshot);
  assert.deepEqual(Object.keys(contract), [
    "contractId",
    "version",
    "layout",
    "typography",
    "colors",
    "surface",
    "interaction",
    "provenance",
    "disclaimers",
  ]);
});

test("Concept A fixes exact shell, typography, color, density, and state values", async () => {
  const contract = await loadContract();

  assert.deepEqual(contract.layout.viewport1440, {
    viewportWidthPx: 1440,
    leftRailPx: 224,
    center: "fluid",
    rightInspectorPx: 320,
    inspectorMode: "docked",
  });
  assert.deepEqual(contract.layout.viewport1024, {
    viewportWidthPx: 1024,
    leftRailPx: 56,
    center: "fluid",
    inspectorMode: "overlay",
    overlayInspectorPx: 360,
  });
  assert.deepEqual(contract.typography, {
    fontFamily: "Noto Sans KR",
    body: { fontSizePx: 13, lineHeightPx: 20 },
    table: { fontSizePx: 12, lineHeightPx: 18 },
  });
  assert.deepEqual(contract.layout.rowHeightsPx, {
    compact: 26,
    regular: 32,
    comfortable: 40,
  });
  assert.deepEqual(contract.colors, {
    background: "#F4F4F4",
    surface: "#FFFFFF",
    text: "#161616",
    secondary: "#525252",
    border: "#D9D9D9",
    accent: "#0F62FE",
    success: "#198038",
    warning: "#F1C21B",
    error: "#DA1E28",
  });
  assert.deepEqual(contract.surface, {
    shape: "square-tonal",
    radiusPx: 0,
    gradient: false,
    roundedCards: false,
  });
  assert.equal(contract.layout.stickyTotals, true);
  assert.deepEqual(contract.interaction.keyboard.keys, [
    "Tab",
    "Shift+Tab",
    "Enter",
    "Escape",
    "ArrowUp",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
  ]);
  assert.deepEqual(contract.interaction.ime, {
    compositionStart: "defer-validation",
    compositionEnd: "commit-and-validate",
  });
  assert.deepEqual(contract.interaction.focus, {
    visible: true,
    outlinePx: 3,
    restoreAfterOverlayClose: true,
  });
  assert.deepEqual(contract.interaction.accessibility, {
    primaryControlMinSizePx: 44,
    liveRegion: "aria-live",
    statusUpdates: true,
  });
  assert.deepEqual(contract.provenance.koreaNet.selection, {
    requiresSpecPass: true,
    requiresSupplierLocationEvidence: true,
    requiresServiceAreaEvidence: true,
    chooseLowestEligiblePrice: true,
    tiesChooseJointLowest: true,
    noAutomaticSelectionWithoutEvidence: true,
  });
  assert.deepEqual(contract.provenance.koreaNet.requiredFields, [
    "productId",
    "supplierName",
    "unitPriceWon",
    "unit",
    "specSnapshot",
    "sourceUrl",
    "apiOperation",
    "observedAt",
    "sourcePayloadSha256",
    "supplierLocationEvidence",
    "serviceAreaEvidence",
  ]);
  assert.deepEqual(contract.disclaimers, {
    always: "내부 비상업 검토용 · 법적 인증 아님 · 최신성 보장 없음",
    unsigned:
      "주의: 코드 서명되지 않은 시험 빌드임. 운영체제가 배포자 신원을 검증하지 못함.",
  });
});

test("DESIGN.md names every machine-readable contract string", async () => {
  const contract = await loadContract();
  const docs = readFileSync(docsPath, "utf8");
  const missing = [...new Set(collectStringValues(contract))].filter(
    (value) => !docs.includes(value),
  );
  assert.deepEqual(missing, []);
});

test("forbidden gradient fixture is rejected by the real design validator", () => {
  assert.equal(existsSync(validatorPath), true, "design validator must exist");
  assert.equal(existsSync(forbiddenFixturePath), true, "forbidden fixture must exist");

  const result = spawnSync(process.execPath, [validatorPath, "--fixture", forbiddenFixturePath], {
    cwd: root,
    encoding: "utf8",
  });
  assert.notEqual(result.status, 0);
  assert.match(`${result.stdout}\n${result.stderr}`, /DESIGN_FORBIDDEN_STYLE:gradient/);
});

test("rounded-card semantics are rejected by the same validator", () => {
  const tempDir = mkdtempSync(resolve(root, ".design-contract-test-"));
  const fixturePath = resolve(tempDir, "rounded-card.json");
  writeFileSync(
    fixturePath,
    JSON.stringify({ surface: { radiusPx: 8, roundedCards: true } }),
    "utf8",
  );
  try {
    const result = spawnSync(process.execPath, [validatorPath, "--fixture", fixturePath], {
      cwd: root,
      encoding: "utf8",
    });
    assert.notEqual(result.status, 0);
    assert.match(`${result.stdout}\n${result.stderr}`, /DESIGN_FORBIDDEN_STYLE:rounded-card/);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});
