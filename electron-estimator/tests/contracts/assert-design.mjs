import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const root = resolve(import.meta.dirname, "../..");
const contractPath = resolve(root, "src/renderer/design-contract.ts");
const fixtureIndex = process.argv.indexOf("--fixture");
const fixturePath = fixtureIndex >= 0 ? process.argv[fixtureIndex + 1] : undefined;

if (fixturePath === undefined) {
  console.error("DESIGN_FIXTURE_REQUIRED");
  process.exitCode = 2;
} else {
  const { DESIGN_CONTRACT } = await import(pathToFileURL(contractPath).href);
  const fixture = JSON.parse(readFileSync(resolve(process.cwd(), fixturePath), "utf8"));
  const surfaces = [DESIGN_CONTRACT.surface, fixture.surface ?? {}];
  const violations = [];

  for (const surface of surfaces) {
    if (surface.gradient === true) violations.push("gradient");
    if (surface.roundedCards === true || surface.radiusPx > 0) {
      violations.push("rounded-card");
    }
  }

  if (violations.length > 0) {
    for (const violation of [...new Set(violations)]) {
      console.error(`DESIGN_FORBIDDEN_STYLE:${violation}`);
    }
    process.exitCode = 1;
  } else {
    console.log("DESIGN_VALID");
  }
}
