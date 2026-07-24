import {
  completeEstimateSync,
  failEstimateSync,
  getPendingEstimates,
} from "./db.js";

let activeSync = null;

export function syncPendingEstimates(fetchImplementation = globalThis.fetch, onSynced = () => {}) {
  if (activeSync !== null) {
    return activeSync.then(() => syncPendingEstimates(fetchImplementation, onSynced));
  }
  activeSync = (async () => {
    try {
      const pending = await getPendingEstimates();
      for (const record of pending) {
        try {
          const url = `/api/estimates/${encodeURIComponent(record.id)}`;
          let response;
          if (record.deleted) {
            response = await fetchImplementation(url, { method: "DELETE" });
          } else {
            const { title, lines } = record.document;
            response = await fetchImplementation(url, {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ title, lines }),
            });
          }
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
          }
          await completeEstimateSync(record);
          onSynced(record.id);
        } catch (error) {
          await failEstimateSync(
            record,
            error instanceof Error ? error.message : String(error),
          );
        }
      }
    } finally {
      activeSync = null;
    }
  })();
  return activeSync;
}
