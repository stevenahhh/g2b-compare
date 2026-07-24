import { exportLegacyWorkbook } from "../../src/legacy/export/index.js";
import { exportFixture } from "./atomic-export-fixtures.js";

const destinationDirectory = process.argv[2];
const journalRoot = process.argv[3];
if (destinationDirectory === undefined || journalRoot === undefined) {
  throw new TypeError("KILL_CHILD_ARGUMENT_REQUIRED");
}

const request = await exportFixture(
  "A",
  destinationDirectory,
  "killed-A"
);
let renameStages = 0;
const result = await exportLegacyWorkbook(request, {
  journalRoot,
  beforeStage: async (stage) => {
    if (stage === "rename-workbook" || stage === "rename-report") {
      renameStages += 1;
      if (renameStages === 2) {
        process.stdout.write("READY\n");
        await new Promise<void>(() => undefined);
      }
    }
  }
});

process.stdout.write(`${JSON.stringify(result)}\n`);
