import "fake-indexeddb/auto";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DATABASE_NAME,
  deleteEstimate,
  getEstimate,
  putEstimate,
  putSyncedEstimate,
} from "./db.js";
import { syncPendingEstimates } from "./sync.js";

function deleteTestDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.deleteDatabase(DATABASE_NAME);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
}

afterEach(() => deleteTestDatabase());

describe("latest-state estimate replay", () => {
  it("sends one PUT containing the latest document after repeated edits", async () => {
    // Given: multiple local edits coalesced under one estimate ID.
    const id = "d".repeat(32);
    await putEstimate({ id, title: "First", lines: [{ id: "3".repeat(32), quantity: 1 }] });
    const latest = { id, title: "Latest", lines: [{ id: "3".repeat(32), quantity: 7 }] };
    await putEstimate(latest);
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));

    // When: pending estimates are replayed.
    await syncPendingEstimates(fetchMock);

    // Then: exactly one PUT carries the latest full document.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(`/api/estimates/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: latest.title, lines: latest.lines }),
    });
  });

  it("sends DELETE instead of PUT for a deleted estimate", async () => {
    // Given: a local edit followed by deletion.
    const id = "e".repeat(32);
    await putSyncedEstimate({ id, title: "Gone", lines: [{ id: "4".repeat(32), quantity: 1 }] });
    await deleteEstimate(id);
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));

    // When: the tombstone is replayed.
    await syncPendingEstimates(fetchMock);

    // Then: one DELETE is sent and the tombstone is removed.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(`/api/estimates/${id}`, { method: "DELETE" });
    await expect(getEstimate(id)).resolves.toBeUndefined();
  });

  it("sends no DELETE for an empty never-synced draft", async () => {
    // Given: an empty browser-only draft deleted before any sync.
    const id = "1".repeat(32);
    await putEstimate({ id, title: "", lines: [] });
    await deleteEstimate(id);
    const fetchMock = vi.fn();

    // When: pending estimates are replayed.
    await syncPendingEstimates(fetchMock);

    // Then: no request or local tombstone exists.
    expect(fetchMock).not.toHaveBeenCalled();
    await expect(getEstimate(id)).resolves.toBeUndefined();
  });

  it("coalesces overlapping sync calls into one active request", async () => {
    // Given: one pending estimate and a request held open by the test.
    const id = "2".repeat(32);
    await putEstimate({ id, title: "Once", lines: [{ id: "9".repeat(32), quantity: 1 }] });
    let releaseRequest;
    const response = new Promise((resolve) => {
      releaseRequest = () => resolve(new Response(null, { status: 200 }));
    });
    const fetchMock = vi.fn().mockReturnValue(response);

    // When: two sync calls overlap in the same tab.
    const first = syncPendingEstimates(fetchMock);
    const second = syncPendingEstimates(fetchMock);
    releaseRequest();
    await Promise.all([first, second]);

    // Then: both callers share one active run and one network request.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("runs a queued pass for a change added during an active sync", async () => {
    // Given: one request is active when a second estimate becomes pending.
    const firstId = "a".repeat(32);
    const secondId = "b".repeat(32);
    await putEstimate({ id: firstId, title: "First", lines: [{ id: "1".repeat(32), quantity: 1 }] });
    let releaseFirstRequest;
    const firstResponse = new Promise((resolve) => {
      releaseFirstRequest = () => resolve(new Response(null, { status: 200 }));
    });
    const fetchMock = vi.fn()
      .mockReturnValueOnce(firstResponse)
      .mockResolvedValue(new Response(null, { status: 200 }));
    const firstSync = syncPendingEstimates(fetchMock);
    await putEstimate({ id: secondId, title: "Second", lines: [{ id: "2".repeat(32), quantity: 1 }] });

    // When: a second sync is requested before the first finishes.
    const secondSync = syncPendingEstimates(fetchMock);
    releaseFirstRequest();
    await Promise.all([firstSync, secondSync]);

    // Then: the later pending estimate is sent by a queued pass.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await expect(getEstimate(secondId)).resolves.toMatchObject({ pendingSync: false });
  });

  it("notifies after a pending estimate is stored as synced", async () => {
    // Given: one pending estimate and a successful server response.
    const id = "c".repeat(32);
    await putEstimate({ id, title: "Saved", lines: [{ id: "3".repeat(32), quantity: 1 }] });
    const onSynced = vi.fn();

    // When: replay completes.
    await syncPendingEstimates(
      vi.fn().mockResolvedValue(new Response(null, { status: 200 })),
      onSynced,
    );

    // Then: the UI receives the persisted estimate ID after local state is clear.
    expect(onSynced).toHaveBeenCalledWith(id);
    await expect(getEstimate(id)).resolves.toMatchObject({ pendingSync: false });
  });

  it("retains the latest mutation and one error string after failure", async () => {
    // Given: one pending latest document and an HTTP failure.
    const document = {
      id: "f".repeat(32),
      title: "Retry",
      lines: [{ id: "5".repeat(32), quantity: 3 }],
    };
    await putEstimate(document);
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 500 }));

    // When: replay fails.
    await syncPendingEstimates(fetchMock);

    // Then: local data stays pending with a retryable error.
    await expect(getEstimate(document.id)).resolves.toEqual({
      id: document.id,
      document,
      everSynced: false,
      pendingSync: true,
      deleted: false,
      error: "HTTP 500",
    });
  });

  it("clears pending state and error after a successful PUT", async () => {
    // Given: a pending document whose earlier replay failed.
    const document = {
      id: "0".repeat(32),
      title: "Saved",
      lines: [{ id: "6".repeat(32), quantity: 5 }],
    };
    await putEstimate(document);
    await syncPendingEstimates(vi.fn().mockRejectedValue(new Error("offline")));

    // When: retry succeeds.
    await syncPendingEstimates(vi.fn().mockResolvedValue(new Response(null, { status: 200 })));

    // Then: the latest document remains while pending and error are cleared.
    await expect(getEstimate(document.id)).resolves.toEqual({
      id: document.id,
      document,
      everSynced: true,
      pendingSync: false,
      deleted: false,
      error: null,
    });
  });

  it("keeps a newer edit pending when an older PUT finishes", async () => {
    // Given: a pending document that changes while its request is active.
    const id = "7".repeat(32);
    await putEstimate({ id, title: "Sending", lines: [{ id: "8".repeat(32), quantity: 1 }] });
    const latest = { id, title: "Changed", lines: [{ id: "8".repeat(32), quantity: 9 }] };
    const fetchMock = vi.fn().mockImplementation(async () => {
      await putEstimate(latest);
      return new Response(null, { status: 200 });
    });

    // When: the older snapshot reports success.
    await syncPendingEstimates(fetchMock);

    // Then: success does not clear the newer local mutation.
    await expect(getEstimate(id)).resolves.toMatchObject({
      document: latest,
      pendingSync: true,
      deleted: false,
      error: null,
    });
  });
});
