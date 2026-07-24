export const DATABASE_NAME = "g2b-spa";
export const DATABASE_VERSION = 1;

function requestResult(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function transactionDone(transaction) {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}

export function openDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      database.createObjectStore("catalog_cache", { keyPath: "key" });
      database.createObjectStore("estimates", { keyPath: "id" });
      database.createObjectStore("app_state", { keyPath: "name" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withStore(storeName, mode, operation) {
  const database = await openDatabase();
  const transaction = database.transaction(storeName, mode);
  const completion = transactionDone(transaction);
  try {
    const result = await operation(transaction.objectStore(storeName));
    await completion;
    return result;
  } finally {
    database.close();
  }
}

export function putCatalogCache(key, value) {
  return withStore("catalog_cache", "readwrite", (store) =>
    requestResult(store.put({ key, value })),
  );
}

export async function getCatalogCache(key) {
  const record = await withStore("catalog_cache", "readonly", (store) =>
    requestResult(store.get(key)),
  );
  return record?.value;
}

export function putAppState(name, value) {
  return withStore("app_state", "readwrite", (store) =>
    requestResult(store.put({ name, value })),
  );
}

export async function getAppState(name) {
  const record = await withStore("app_state", "readonly", (store) =>
    requestResult(store.get(name)),
  );
  return record?.value;
}

export function putEstimate(document) {
  return withStore("estimates", "readwrite", async (store) => {
    const current = await requestResult(store.get(document.id));
    await requestResult(
      store.put({
        id: document.id,
        document,
        everSynced: current?.everSynced === true,
        pendingSync: document.lines.length > 0,
        deleted: false,
        error: null,
      }),
    );
  });
}
export function putSyncedEstimate(document) {
  return withStore("estimates", "readwrite", (store) =>
    requestResult(
      store.put({
        id: document.id,
        document,
        everSynced: true,
        pendingSync: false,
        deleted: false,
        error: null,
      }),
    ),
  );
}

export function getEstimate(id) {
  return withStore("estimates", "readonly", (store) => requestResult(store.get(id)));
}

export function getAllEstimates() {
  return withStore("estimates", "readonly", (store) => requestResult(store.getAll()));
}

export async function getPendingEstimates() {
  const records = await getAllEstimates();
  return records.filter((record) => record.pendingSync);
}

export function deleteEstimate(id) {
  return withStore("estimates", "readwrite", async (store) => {
    const record = await requestResult(store.get(id));
    if (record === undefined) {
      return;
    }
    if (!record.everSynced) {
      await requestResult(store.delete(id));
      return;
    }
    await requestResult(
      store.put({ ...record, pendingSync: true, deleted: true, error: null }),
    );
  });
}

function isSamePendingState(current, snapshot) {
  return (
    current.pendingSync === true &&
    current.deleted === snapshot.deleted &&
    JSON.stringify(current.document) === JSON.stringify(snapshot.document)
  );
}

export function completeEstimateSync(snapshot) {
  return withStore("estimates", "readwrite", async (store) => {
    const current = await requestResult(store.get(snapshot.id));
    if (current === undefined || !isSamePendingState(current, snapshot)) {
      return;
    }
    if (snapshot.deleted) {
      await requestResult(store.delete(snapshot.id));
      return;
    }
    await requestResult(
      store.put({ ...current, everSynced: true, pendingSync: false, error: null }),
    );
  });
}

export function failEstimateSync(snapshot, error) {
  return withStore("estimates", "readwrite", async (store) => {
    const current = await requestResult(store.get(snapshot.id));
    if (current === undefined || !isSamePendingState(current, snapshot)) {
      return;
    }
    await requestResult(store.put({ ...current, error }));
  });
}
