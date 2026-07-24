import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

async function read(relativePath: string): Promise<string> {
  return readFile(path.resolve(relativePath), "utf8");
}

describe("Given production Electron artifacts", () => {
  it("contains no test repository dependency-injection seam", async () => {
    const [source, bundle] = await Promise.all([
      read("src/main/ipc.ts"),
      read("dist/main/index.js")
    ]);

    for (const text of [source, bundle]) {
      expect(text).not.toContain("IpcDependencies");
      expect(text).not.toContain("DEFAULT_DEPENDENCIES");
      expect(text).not.toContain("dependencies.loadOfficialRepository");
    }
  });

  it("contains no synthetic renderer showcase markers", async () => {
    const [entry, bundle] = await Promise.all([
      read("src/renderer/index.ts"),
      read("dist/renderer/assets/index.js")
    ]);
    const markers = [
      "renderPrimitiveShowcase",
      "primitive-showcase",
      "125,000원",
      "조건 충족 시 자동선택"
    ];

    for (const marker of markers) {
      expect(entry).not.toContain(marker);
      expect(bundle).not.toContain(marker);
    }
    expect(entry).not.toContain("12345678");
    expect(bundle).not.toMatch(/[`'"]12345678[`'"]/u);
  });
});
