import { describe, expect, it } from "vitest";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { importLegacyWorkbook } from "../../src/legacy/import.js";
import {
  LegacySessionError,
  LegacySessionStore
} from "../../src/main/legacy-session.js";
import { ExportRequestSchema } from "../../src/main/ipc-contracts.js";

const SOURCE_NAME =
  "250725-전남 광양시 아트케이션 관광스테이 확충사업 CCTV 설비 내역서.xlsx";
const SOURCE_PATH = path.resolve("..", "dataset", SOURCE_NAME);
const MANIFEST_ROOT = path.resolve("resources", "manifests", "legacy");

describe("Given a main-owned legacy workbook session", () => {
  it("keeps the source path out of the renderer DTO and binds access to its frame", async () => {
    const imported = await importLegacyWorkbook(SOURCE_PATH, {
      manifestRoot: pathToFileURL(`${MANIFEST_ROOT}${path.sep}`)
    });
    const store = new LegacySessionStore();
    const frame = { processId: 11, routingId: 13 };
    const session = store.create({
      sourcePath: SOURCE_PATH,
      sourceName: SOURCE_NAME,
      imported,
      frame
    });

    expect(Reflect.has(session, "sourcePath")).toBe(false);
    expect(() =>
      store.get(session.sessionId, { processId: 11, routingId: 99 })
    ).toThrowError(LegacySessionError);
    expect(store.get(session.sessionId, frame).sourcePath).toBe(SOURCE_PATH);
    const replacement = store.create({
      sourcePath: SOURCE_PATH,
      sourceName: SOURCE_NAME,
      imported,
      frame
    });
    expect(() => store.get(session.sessionId, frame)).toThrowError(
      LegacySessionError
    );
    expect(store.get(replacement.sessionId, frame).sourcePath).toBe(SOURCE_PATH);
  });

  it.each(["sourcePath", "destination", "sourceSha256"])(
    "rejects renderer-injected %s",
    (field) => {
      const request = {
        kind: "legacy_workbook",
        capabilityId: "4e75846a-fc7a-4a09-a4d6-3f8fd73cae3e",
        sessionId: "cc50385d-7fa1-401d-82eb-6c98ad6f970d",
        itemCount: 0,
        cells: [],
        disclaimerChecked: true,
        [field]: "C:\\forged\\source.xlsx"
      };

      expect(ExportRequestSchema.safeParse(request).success).toBe(false);
    }
  );
});
