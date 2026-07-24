import {
  copyFile,
  mkdir,
  readdir,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import { spawn } from "node:child_process";
import { basename, join, resolve } from "node:path";

const KEY_SHEETS = [
  {
    prefix: "A-",
    profile: "A",
    sheet: "자재내역서",
    manifestRange: "B1:R31",
    screenshotBounds: {
      minWidth: 1_600,
      maxWidth: 3_200,
      minHeight: 700,
      maxHeight: 1_500
    }
  },
  {
    prefix: "B-",
    profile: "B",
    sheet: "관급내역서",
    manifestRange: "A1:W25",
    screenshotBounds: {
      minWidth: 1_600,
      maxWidth: 3_200,
      minHeight: 700,
      maxHeight: 1_600
    }
  },
  {
    prefix: "C-",
    profile: "C",
    sheet: "관급내역서",
    manifestRange: "A1:W41",
    screenshotBounds: {
      minWidth: 1_600,
      maxWidth: 3_200,
      minHeight: 1_100,
      maxHeight: 2_200
    }
  },
  {
    prefix: "native-",
    profile: "native",
    sheet: "요약",
    manifestRange: "A1:E204",
    screenshotBounds: {
      minWidth: 500,
      maxWidth: 1_000,
      minHeight: 3_500,
      maxHeight: 5_000
    }
  }
];
const ERROR_SEARCH = "#REF!|#DIV/0!|#VALUE!|#NAME\\?";

export async function runArtifactQa(options) {
  const inputDirectory = resolve(options.inputDirectory);
  const outputDirectory = resolve(options.outputDirectory);
  await mkdir(outputDirectory, { recursive: true });
  const { FileBlob, SpreadsheetFile } = await import("@oai/artifact-tool");
  const files = (await readdir(inputDirectory))
    .filter((name) => name.endsWith(".xlsx"))
    .toSorted();
  if (files.length !== 4) {
    throw new TypeError(`ARTIFACT_QA_EXPECTED_FOUR:${files.length}`);
  }
  const workbooks = [];
  for (const filename of files) {
    const inputPath = resolve(inputDirectory, filename);
    const workbook = await SpreadsheetFile.importXlsx(
      await FileBlob.load(inputPath)
    );
    const inspect = await workbook.inspect({
      kind: "workbook,sheet,table",
      maxChars: 12_000,
      tableMaxRows: 8,
      tableMaxCols: 12,
      tableMaxCellChars: 80
    });
    const errors = await workbook.inspect({
      kind: "match",
      searchTerm: ERROR_SEARCH,
      options: { useRegex: true, maxResults: 500 },
      summary: "task 15 formula error inventory"
    });
    const profile = KEY_SHEETS.find((entry) =>
      filename.startsWith(entry.prefix)
    );
    if (profile === undefined) {
      throw new TypeError(`ARTIFACT_QA_PROFILE_UNKNOWN:${filename}`);
    }
    const keyRegion = await workbook.inspect({
      kind: "region",
      sheetId: profile.sheet,
      range: profile.manifestRange,
      maxChars: 6_000
    });
    const preview = await workbook.render({
      sheetName: profile.sheet,
      autoCrop: "all",
      scale: 1,
      format: "png"
    });
    const previewBytes = new Uint8Array(await preview.arrayBuffer());
    const stem = basename(filename, ".xlsx");
    const inspectPath = resolve(outputDirectory, `${stem}.inspect.ndjson`);
    const errorPath = resolve(outputDirectory, `${stem}.formula-errors.ndjson`);
    const regionPath = resolve(outputDirectory, `${stem}.key-region.ndjson`);
    const previewPath = resolve(
      outputDirectory,
      `${stem}.${profile.sheet}.png`
    );
    await Promise.all([
      writeFile(inspectPath, `${inspect.ndjson}\n`, "utf8"),
      writeFile(errorPath, `${errors.ndjson}\n`, "utf8"),
      writeFile(regionPath, `${keyRegion.ndjson}\n`, "utf8"),
      writeFile(previewPath, previewBytes)
    ]);
    const dimensions = pngDimensions(previewBytes);
    assertScreenshotWithinProfile(filename, dimensions);
    workbooks.push({
      status: "pass",
      profile: profile.profile,
      filename,
      keySheet: profile.sheet,
      manifestRange: profile.manifestRange,
      screenshotBounds: profile.screenshotBounds,
      inspectPath,
      errorPath,
      regionPath,
      previewPath,
      screenshot: dimensions
    });
  }
  const receipt = {
    schemaVersion: "task-15-artifact-qa-v1",
    status: "pass",
    workbookCount: workbooks.length,
    workbooks
  };
  await writeFile(
    resolve(outputDirectory, "task-15-artifact-qa.json"),
    `${JSON.stringify(receipt, null, 2)}\n`,
    "utf8"
  );
  return receipt;
}

export function assertScreenshotWithinProfile(filename, dimensions) {
  const profile = KEY_SHEETS.find((entry) =>
    filename.startsWith(entry.prefix)
  );
  if (profile === undefined) {
    throw new TypeError(`ARTIFACT_QA_PROFILE_UNKNOWN:${filename}`);
  }
  const bounds = profile.screenshotBounds;
  if (
    dimensions.width < bounds.minWidth ||
    dimensions.width > bounds.maxWidth ||
    dimensions.height < bounds.minHeight ||
    dimensions.height > bounds.maxHeight
  ) {
    throw new TypeError(`ARTIFACT_QA_RENDER_DIMENSIONS:${filename}`);
  }
  return Object.freeze({
    profile: profile.profile,
    manifestRange: profile.manifestRange,
    screenshotBounds: bounds
  });
}

function pngDimensions(bytes) {
  if (
    bytes.length < 24 ||
    String.fromCharCode(...bytes.slice(1, 4)) !== "PNG"
  ) {
    throw new TypeError("ARTIFACT_QA_INVALID_PNG");
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  return {
    width: view.getUint32(16, false),
    height: view.getUint32(20, false)
  };
}

async function bootstrap(options) {
  const runtimeDirectory = resolve(options.outputDirectory, ".artifact-runtime");
  const runnerPath = resolve(runtimeDirectory, "artifact-qa.mjs");
  const moduleLink = resolve(runtimeDirectory, "node_modules");
  await rm(runtimeDirectory, { recursive: true, force: true });
  await mkdir(runtimeDirectory, { recursive: true });
  await copyFile(import.meta.filename, runnerPath);
  await symlink(resolve(options.runtimeModules), moduleLink, "junction");
  const exitCode = await new Promise((resolveExit, reject) => {
    const child = spawn(resolve(options.runtimeNode), [
      runnerPath,
      "--input",
      options.inputDirectory,
      "--out",
      options.outputDirectory,
      "--runtime-node",
      options.runtimeNode,
      "--runtime-modules",
      options.runtimeModules
    ], {
      env: { ...process.env, TASK15_ARTIFACT_WORKER: "1" },
      stdio: "inherit",
      windowsHide: true
    });
    child.once("error", reject);
    child.once("exit", (code) => resolveExit(code ?? 1));
  });
  await rm(runtimeDirectory, { recursive: true, force: true });
  if (exitCode !== 0) {
    throw new TypeError(`ARTIFACT_QA_WORKER_FAILED:${exitCode}`);
  }
}

function cliOptions(args) {
  const value = (name) => {
    const index = args.indexOf(name);
    const result = index < 0 ? undefined : args[index + 1];
    if (result === undefined) {
      throw new TypeError(`ARTIFACT_QA_ARGUMENT_REQUIRED:${name}`);
    }
    return result;
  };
  return {
    inputDirectory: value("--input"),
    outputDirectory: value("--out"),
    runtimeNode: value("--runtime-node"),
    runtimeModules: value("--runtime-modules")
  };
}

if (
  process.argv[1] !== undefined &&
  resolve(process.argv[1]) === resolve(import.meta.filename)
) {
  const options = cliOptions(process.argv.slice(2));
  if (process.env["TASK15_ARTIFACT_WORKER"] === "1") {
    console.log(JSON.stringify(await runArtifactQa(options), null, 2));
  } else {
    await bootstrap(options);
  }
}
