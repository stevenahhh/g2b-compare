import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { API } from "typescript/unstable/sync";
import { LanguageVariant, SyntaxKind, isCatchClause } from "typescript/unstable/ast";
import { createScanner } from "typescript/unstable/ast/scanner";

const CATEGORY_NAMES = [
  "any-keyword",
  "duplicate-resource",
  "empty-catch",
  "speculative-config",
  "suppressive-directive"
];
const SOURCE_EXTENSIONS = new Set([".ts", ".js", ".mjs"]);

export async function auditRoot(root) {
  const resolvedRoot = path.resolve(root);
  const violations = [
    ...(await sourceViolations(resolvedRoot)),
    ...(await duplicateResourceViolations(resolvedRoot)),
    ...(await speculativeConfigViolations(resolvedRoot))
  ].sort((left, right) =>
    `${left.code}:${left.path}`.localeCompare(`${right.code}:${right.path}`));
  const categoryCounts = Object.fromEntries(CATEGORY_NAMES.map((name) => [name, 0]));
  for (const violation of violations) categoryCounts[violation.category] += 1;
  return {
    status: violations.length === 0 ? "pass" : "fail",
    violations,
    categoryCounts
  };
}

async function sourceViolations(root) {
  const files = (await sourceFiles(root)).sort();
  const violations = [];
  const api = new API({ cwd: root });
  const snapshot = api.updateSnapshot({ openFiles: files });
  try {
    for (const file of files) {
      const sourceFile = snapshot.getDefaultProjectForFile(file)?.program.getSourceFile(file);
      if (sourceFile === undefined) throw new TypeError(`SOURCE_FILE_MISSING:${file}`);
      const relativePath = path.relative(root, file).replaceAll("\\", "/");
      const scanner = createScanner(false, LanguageVariant.Standard, sourceFile.text);
      for (let token = scanner.scan(); token !== SyntaxKind.EndOfFile; token = scanner.scan()) {
        continue;
      }
      for (const directive of scanner.getCommentDirectives() ?? []) {
        const position = directive.range.pos;
        violations.push({
          code: "SUPPRESSIVE_DIRECTIVE",
          category: "suppressive-directive",
          path: relativePath,
          line: sourceFile.getLineAndCharacterOfPosition(position).line + 1
        });
      }
      const visit = (node) => {
        if (node.kind === SyntaxKind.AnyKeyword) {
          violations.push({ code: "ANY_KEYWORD", category: "any-keyword", path: relativePath,
            line: sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1 });
        }
        if (isCatchClause(node) && node.block.statements.length === 0) {
          violations.push({ code: "EMPTY_CATCH", category: "empty-catch", path: relativePath,
            line: sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1 });
        }
        node.forEachChild(visit);
      };
      visit(sourceFile);
    }
  } finally {
    snapshot.dispose();
    api.close();
  }
  return violations;
}

async function duplicateResourceViolations(root) {
  const files = (await Promise.all(["data", "manifests", "observations", "sources"].map(
    (directory) => filesUnder(path.join(root, "resources", directory))
  ))).flat();
  const groups = new Map();
  for (const file of files) {
    const digest = createHash("sha256").update(await readFile(file)).digest("hex");
    const group = groups.get(digest) ?? [];
    group.push(file);
    groups.set(digest, group);
  }
  return [...groups.values()]
    .filter((filesWithDigest) => filesWithDigest.length > 1)
    .map((filesWithDigest) => ({
      code: "DUPLICATE_RESOURCE",
      category: "duplicate-resource",
      path: path.relative(root, filesWithDigest.sort()[0]).replaceAll("\\", "/"),
      files: filesWithDigest.map((file) => path.relative(root, file).replaceAll("\\", "/")).sort()
    }));
}

async function speculativeConfigViolations(root) {
  const entries = await readdir(root, { withFileTypes: true });
  const packageJson = JSON.parse(await readFile(path.join(root, "package.json"), "utf8"));
  const scripts = Object.values(packageJson.scripts ?? []).join("\n");
  const configs = entries.filter((entry) => entry.isFile() && /^tsconfig(?:[.-].+)?\.json$/u.test(entry.name));
  const configTexts = await Promise.all(configs.map(async (entry) => ({
    name: entry.name,
    text: await readFile(path.join(root, entry.name), "utf8")
  })));
  return configTexts
    .filter(({ name }) => name !== "tsconfig.json")
    .filter(({ name }) => !scripts.includes(name))
    .filter(({ name }) => !configTexts.some((config) =>
      config.name !== name && config.text.includes(`\"./${name}\"`)))
    .map(({ name }) => ({ code: "SPECULATIVE_CONFIG", category: "speculative-config", path: name }));
}

async function sourceFiles(root) {
  const directories = ["src", "scripts", "tests"];
  return (await Promise.all(directories.map((directory) => filesUnder(path.join(root, directory))))).flat()
    .filter((file) => SOURCE_EXTENSIONS.has(path.extname(file)));
}

async function filesUnder(directory) {
  let entries;
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") return [];
    throw error;
  }
  return (await Promise.all(entries.map(async (entry) => {
    const candidate = path.join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(candidate) : [candidate];
  }))).flat();
}

const invokedFile = process.argv[1];
if (invokedFile !== undefined && import.meta.url === pathToFileURL(path.resolve(invokedFile)).href) {
  const result = await auditRoot(path.resolve(import.meta.dirname, ".."));
  process.stdout.write(`${JSON.stringify(result)}\n`);
  if (result.status !== "pass") process.exitCode = 1;
}
