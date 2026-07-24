import "fake-indexeddb/auto";

import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it } from "vitest";

import {
  DATABASE_NAME,
  completeEstimateSync,
  deleteEstimate,
  getAllEstimates,
  getAppState,
  getCatalogCache,
  getEstimate,
  getPendingEstimates,
  failEstimateSync,
  openDatabase,
  putAppState,
  putCatalogCache,
  putEstimate,
  putSyncedEstimate,
} from "./db.js";

function deleteTestDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.deleteDatabase(DATABASE_NAME);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
}

afterEach(() => deleteTestDatabase());

describe("IndexedDB latest-state storage", () => {
  it("creates exactly the three locked stores", async () => {
    // Given: no existing application database.
    // When: version 1 is opened.
    const database = await openDatabase();

    try {
      // Then: only the locked key-path stores exist.
      const storeNames = Array.from(database.objectStoreNames);
      expect(storeNames).toEqual(["app_state", "catalog_cache", "estimates"]);
      const transaction = database.transaction(storeNames);
      expect(transaction.objectStore("catalog_cache").keyPath).toBe("key");
      expect(transaction.objectStore("estimates").keyPath).toBe("id");
      expect(transaction.objectStore("app_state").keyPath).toBe("name");
    } finally {
      database.close();
    }
  });

  it("keeps source limited to the locked schema and mechanisms", () => {
    // Given: the complete persistence and replay source.
    const databaseSource = readFileSync(new URL("./db.js", import.meta.url), "utf8");
    const syncSource = readFileSync(new URL("./sync.js", import.meta.url), "utf8");

    // When: schema declarations and prohibited mechanism names are inspected.
    const stores = Array.from(
      databaseSource.matchAll(/createObjectStore\("([^"]+)"/g),
      (match) => match[1],
    ).sort();

    // Then: exactly three stores exist and no wider offline system is present.
    expect(stores).toEqual(["app_state", "catalog_cache", "estimates"]);
    expect(`${databaseSource}\n${syncSource}`).not.toMatch(
      /queue|meta|sequence|revision|mutation|web\s*lock|navigator\.locks|broadcastchannel|lru/i,
    );
  });

  it("restores cached catalog and UI state after reopening", async () => {
    // Given: persisted catalog and route state.
    await putCatalogCache("camera|price|1", { items: [{ id: "product-1" }] });
    await putAppState("catalog", { route: "/", query: "camera", scrollTop: 320 });

    // When: a fresh database connection reads both values.
    const database = await openDatabase();
    database.close();

    // Then: the identical values are restored.
    await expect(getCatalogCache("camera|price|1")).resolves.toEqual({
      items: [{ id: "product-1" }],
    });
    await expect(getAppState("catalog")).resolves.toEqual({
      route: "/",
      query: "camera",
      scrollTop: 320,
    });
  });

  it("overwrites repeated edits with one latest estimate record", async () => {
    // Given: two full-document edits for one estimate ID.
    await putEstimate({
      id: "a".repeat(32),
      title: "First",
      lines: [{ id: "1".repeat(32), quantity: 1 }],
    });

    // When: the later edit is stored.
    await putEstimate({
      id: "a".repeat(32),
      title: "Latest",
      lines: [{ id: "1".repeat(32), quantity: 4 }],
    });

    // Then: one pending record contains only the latest full document.
    const records = await getAllEstimates();
    expect(records).toHaveLength(1);
    expect(records[0]).toEqual({
      id: "a".repeat(32),
      document: {
        id: "a".repeat(32),
        title: "Latest",
        lines: [{ id: "1".repeat(32), quantity: 4 }],
      },
      everSynced: false,
      pendingSync: true,
      deleted: false,
      error: null,
    });
  });

  it("stores a hydrated server estimate without scheduling a replay", async () => {
    const document = {
      id: "e".repeat(32),
      title: "Server estimate",
      lines: [{ id: "5".repeat(32), quantity: 1 }],
    };

    await putSyncedEstimate(document);

    await expect(getEstimate(document.id)).resolves.toEqual({
      id: document.id,
      document,
      everSynced: true,
      pendingSync: false,
      deleted: false,
      error: null,
    });
    await expect(getPendingEstimates()).resolves.toEqual([]);
  });

  it("gives deletion precedence over the latest edit", async () => {
    // Given: a pending estimate with a latest document.
    const document = {
      id: "b".repeat(32),
      title: "Delete me",
      lines: [{ id: "2".repeat(32), quantity: 2 }],
    };
    await putSyncedEstimate(document);
    await putEstimate(document);

    // When: that estimate is deleted locally.
    await deleteEstimate(document.id);

    // Then: the same record is a pending deletion tombstone.
    await expect(getEstimate(document.id)).resolves.toEqual({
      id: document.id,
      document,
      everSynced: true,
      pendingSync: true,
      deleted: true,
      error: null,
    });
  });

  it("does not mark an empty draft pending", async () => {
    // Given: an empty browser-only draft.
    const document = { id: "c".repeat(32), title: "", lines: [] };

    // When: the draft is stored for restoration.
    await putEstimate(document);

    // Then: it is retained locally but excluded from replay.
    await expect(getEstimate(document.id)).resolves.toMatchObject({
      document,
      everSynced: false,
      pendingSync: false,
      deleted: false,
      error: null,
    });
    await expect(getPendingEstimates()).resolves.toEqual([]);
  });

  it("removes a never-synced estimate instead of creating a tombstone", async () => {
    // Given: a local estimate that has not reached the server.
    const document = {
      id: "d".repeat(32),
      title: "Local",
      lines: [{ id: "3".repeat(32), quantity: 1 }],
    };
    await putEstimate(document);

    // When: the draft is deleted locally.
    await deleteEstimate(document.id);

    // Then: no record remains eligible for replay.
    await expect(getEstimate(document.id)).resolves.toBeUndefined();
    await expect(getPendingEstimates()).resolves.toEqual([]);
  });

  it("does not settle an estimate that is no longer pending", async () => {
    // Given: a pending replay snapshot that completes.
    const document = {
      id: "f".repeat(32),
      title: "Pending",
      lines: [{ id: "4".repeat(32), quantity: 1 }],
    };
    await putEstimate(document);
    const snapshot = await getEstimate(document.id);
    await completeEstimateSync(snapshot);

    // When: stale complete and failure callbacks arrive after settlement.
    await completeEstimateSync(snapshot);
    await failEstimateSync(snapshot, "stale failure");

    // Then: completion provenance and state are not overwritten.
    await expect(getEstimate(document.id)).resolves.toEqual({
      id: document.id,
      document,
      everSynced: true,
      pendingSync: false,
      deleted: false,
      error: null,
    });
  });
});
