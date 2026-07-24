import path from "node:path";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { _electron as electron } from "playwright";

const executablePath = path.resolve(
  "release",
  "win-unpacked",
  "Electron Estimator.exe"
);
const source = path.resolve(
  "..",
  "dataset",
  "전남 광양시 아트케이션 관광스테이 확충사업 CCTV 설비 - 내역서(관급)(최종).xlsx"
);
const userDataDirectory = await mkdtemp(
  path.join(tmpdir(), "electron-estimator-smoke-")
);
let application;
try {
  application = await electron.launch({
    executablePath,
    args: [`--user-data-dir=${userDataDirectory}`]
  });
  const page = await application.firstWindow();
  await page.getByTestId("native-workflow").waitFor();
  await application.evaluate(
    ({ dialog }, selectedPath) => {
      Object.defineProperty(dialog, "showOpenDialog", {
        configurable: true,
        value: async () => ({
          canceled: false,
          filePaths: [selectedPath]
        })
      });
    },
    source
  );
  await page.getByTestId("open-legacy-workflow").click();
  await page.getByTestId("import-legacy").click();
  await page.waitForFunction(
    () =>
      document.querySelector('[data-testid="legacy-workflow"]')
        ?.getAttribute("data-profile") === "C"
  );
  const profile = await page.getByTestId("legacy-workflow")
    .getAttribute("data-profile");
  if (profile !== "C") {
    const status = await page.getByTestId("legacy-export-result").innerText();
    throw new TypeError(
      `PACKAGED_LEGACY_IMPORT_FAILED:${String(profile)}:${status}`
    );
  }
  const sourcePathExposed = await page.evaluate(
    (selectedPath) => document.body.innerText.includes(selectedPath),
    source
  );
  if (sourcePathExposed) {
    throw new TypeError("PACKAGED_SOURCE_PATH_EXPOSED");
  }
  console.log(JSON.stringify({
    status: "PACKAGE_RUNTIME_SMOKE_PASS",
    profile,
    sourcePathExposed
  }, null, 2));
} finally {
  await application?.close();
  await rm(userDataDirectory, { force: true, recursive: true });
}
