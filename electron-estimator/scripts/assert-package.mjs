import { listPackage } from "@electron/asar";
import { access } from "node:fs/promises";
import path from "node:path";

const archive = path.resolve(
  process.argv[2] ?? "release/win-unpacked/resources/app.asar"
);
const expected = [
  "resources/data/market-prices.jsonl",
  "resources/data/productivity.jsonl",
  "resources/data/wages.jsonl",
  "resources/manifests/legacy/gwangyang-direct-2025.json",
  "resources/manifests/legacy/gwangyang-procurement-final-2025.json",
  "resources/manifests/legacy/suncheon-procurement-2025.json",
  "resources/observations/manifest.json",
  "resources/observations/observations.json",
  "resources/sources/source-manifest.json"
].toSorted();

await access(archive);
const entries = listPackage(archive).map((entry) =>
  entry.replaceAll("\\", "/").replace(/^\/+/u, "")
);
const resources = entries
  .filter((entry) => /^resources\/.+[.](?:json|jsonl)$/u.test(entry))
  .toSorted();
const forbiddenResources = entries.filter(
  (entry) =>
    entry.startsWith("resources/") &&
    (
      /[.](?:xlsx|xlsm|pdf)$/iu.test(entry) ||
      /(?:^|\/)tests?(?:\/|$)/iu.test(entry)
    )
);
const testPaths = entries.filter(
  (entry) =>
    /(?:^|\/)(?:test|tests|__tests__)(?:\/|$)/iu.test(entry) ||
    /(?:^|\/)[^/]+[.](?:test|spec)[.][^/]+$/iu.test(entry) ||
    /(?:^|\/)(?:test|tests|spec|__tests__)[.][^/]+$/iu.test(entry)
);
const sourceMaps = entries.filter((entry) => /[.]map$/iu.test(entry));
const sourceDocuments = entries.filter(
  (entry) => /[.](?:ts|tsx|mts|cts)$/iu.test(entry)
);
const datasetDocuments = entries.filter(
  (entry) =>
    /(?:^|\/)dataset(?:\/|$)/iu.test(entry) ||
    /[.](?:xlsx|xlsm|pdf)$/iu.test(entry)
);
const secrets = entries.filter(
  (entry) =>
    /(?:^|\/)(?:[.]env(?:[.][^/]*)?|[.]npmrc|id_rsa|credentials(?:[.][^/]*)?|secrets?(?:[.][^/]*)?|[^/]+[.](?:pem|key|pfx|p12))$/iu.test(entry)
);
if (
  JSON.stringify(resources) !== JSON.stringify(expected) ||
  forbiddenResources.length > 0 ||
  testPaths.length > 0 ||
  sourceMaps.length > 0 ||
  sourceDocuments.length > 0 ||
  datasetDocuments.length > 0 ||
  secrets.length > 0
) {
  console.error(JSON.stringify({
    status: "PACKAGE_INVENTORY_MISMATCH",
    expected,
    resources,
    forbiddenResources,
    testPathCount: testPaths.length,
    testPathSample: testPaths.slice(0, 20),
    sourceMapCount: sourceMaps.length,
    sourceMapSample: sourceMaps.slice(0, 20),
    sourceDocumentCount: sourceDocuments.length,
    sourceDocumentSample: sourceDocuments.slice(0, 20),
    datasetDocumentCount: datasetDocuments.length,
    datasetDocumentSample: datasetDocuments.slice(0, 20),
    secretCount: secrets.length,
    secretSample: secrets.slice(0, 20)
  }, null, 2));
  process.exitCode = 1;
} else {
  console.log(JSON.stringify({
    status: "PACKAGE_INVENTORY_PASS",
    resources,
    forbiddenResources,
    testPathCount: 0,
    sourceMapCount: 0,
    sourceDocumentCount: 0,
    datasetDocumentCount: 0,
    secretCount: 0
  }, null, 2));
}
