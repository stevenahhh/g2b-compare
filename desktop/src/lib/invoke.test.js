import { describe, expect, it, vi } from "vitest";

import {
  COMMANDS,
  createCatalogClient,
  createDataClient,
  createDesktopStateClient,
  createDocumentActionClient,
  createEstimateClient,
} from "./invoke";

const page = { items: [], page: 1, page_count: 1, total_count: 0 };

describe("typed Tauri catalog adapter", () => {
  it("maps product and relation requests to narrow commands", async () => {
    const invoke = vi.fn().mockResolvedValue(page);
    const client = createCatalogClient(invoke);

    await client.searchProducts({
      company_name: "주식회사 코리아넷",
      query: "카메라",
      sort: "price_asc",
      page: 1,
    });
    await client.searchRelations({
      parent_product_id: "P0000001",
      company_name: "주식회사 코리아넷",
      category: "selection",
      query: "브래킷",
      sort: "name_asc",
      page: 2,
    });

    expect(invoke).toHaveBeenNthCalledWith(1, COMMANDS.searchProducts, {
      request: {
        company_name: "주식회사 코리아넷",
        query: "카메라",
        sort: "price_asc",
        page: 1,
      },
    });
    expect(invoke).toHaveBeenNthCalledWith(2, COMMANDS.searchRelations, {
      request: {
        parent_product_id: "P0000001",
        company_name: "주식회사 코리아넷",
        category: "selection",
        query: "브래킷",
        sort: "name_asc",
        page: 2,
      },
    });
  });

  it("keeps persistence, add, and external-open parameters typed", async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    const client = createCatalogClient(invoke);
    const state = {
      query: "",
      sort: "price_asc",
      page: 1,
      selected_product_id: null,
      active_category: "selection",
      product_scroll_top: 0,
      relation_scroll_top: { selection: 0, additional: 0, construction: 0 },
      relation_query: { selection: "", additional: "", construction: "" },
      relation_page: { selection: 1, additional: 1, construction: 1 },
    };

    await client.saveView(state);
    await client.addItem({
      product_id: "P1",
      line_kind: "main",
      parent_product_id: null,
      relation_id: null,
    });
    await client.openProduct("https://example.test/P1");
    await client.getCacheStatus();

    expect(invoke).toHaveBeenNthCalledWith(1, COMMANDS.saveCatalogView, { state });
    expect(invoke).toHaveBeenNthCalledWith(2, COMMANDS.addCatalogItem, {
      request: {
        product_id: "P1",
        line_kind: "main",
        parent_product_id: null,
        relation_id: null,
      },
    });
    expect(invoke).toHaveBeenNthCalledWith(3, COMMANDS.openProduct, {
      detailUrl: "https://example.test/P1",
    });
    expect(invoke).toHaveBeenNthCalledWith(4, COMMANDS.getCatalogCacheStatus);
  });
});

describe("typed Tauri data, document, and durable-state adapters", () => {
  it("maps explicit data and document actions to narrow commands", async () => {
    const invoke = vi.fn().mockResolvedValue({});
    const data = createDataClient(invoke);
    const documents = createDocumentActionClient(invoke);

    await data.getDataStatus();
    await data.runDataSync();
    await data.runDataDiagnostics();
    await documents.copyEstimateTable("estimate-1");
    await documents.exportEstimateWorkbook("estimate-1");

    expect(invoke.mock.calls).toEqual([
      [COMMANDS.getDataStatus],
      [COMMANDS.runDataSync],
      [COMMANDS.runDataDiagnostics],
      [COMMANDS.copyEstimateTable, { id: "estimate-1" }],
      [COMMANDS.exportEstimateWorkbook, { id: "estimate-1" }],
    ]);
  });

  it("preserves the durable view and conflict-resolution request shapes", async () => {
    const invoke = vi.fn().mockResolvedValue({});
    const state = createDesktopStateClient(invoke);
    const view = { route: "estimate", path: "/estimates/estimate-1" };

    await state.loadDesktopView();
    await state.saveDesktopView(view);
    await state.getReconciliationStatus();
    await state.replayPendingChanges();
    await state.resolveReconciliationConflict({ sequence: 7, resolution: "keep-local" });

    expect(invoke.mock.calls).toEqual([
      [COMMANDS.loadDesktopView],
      [COMMANDS.saveDesktopView, { state: view }],
      [COMMANDS.getReconciliationStatus],
      [COMMANDS.replayPendingChanges],
      [COMMANDS.resolveReconciliationConflict, { request: { sequence: 7, resolution: "keep-local" } }],
    ]);
  });
});

describe("typed Tauri estimate adapter", () => {
  it("maps list, CRUD, revision, and active-view state to narrow commands", async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    const client = createEstimateClient(invoke);
    const create = {
      id: "a".repeat(32),
      title: "문서",
      template_sha256: "template",
      lines: [],
      comparisons: [],
    };
    const update = {
      expected_revision: 2,
      title: "수정 문서",
      lines: [],
      comparisons: [],
    };

    await client.listEstimates();
    await client.createEstimate(create);
    await client.readEstimate(create.id);
    await client.updateEstimate(create.id, update);
    await client.refreshEstimateComparisons(create.id, { expected_revision: 3 });
    await client.deleteEstimate(create.id);
    await client.loadEstimateView();
    await client.saveEstimateView({ active_estimate_id: create.id });

    expect(invoke.mock.calls).toEqual([
      [COMMANDS.listEstimates],
      [COMMANDS.createEstimate, { request: create }],
      [COMMANDS.readEstimate, { id: create.id }],
      [COMMANDS.updateEstimate, { id: create.id, request: update }],
      [COMMANDS.refreshEstimateComparisons, {
        id: create.id,
        request: { expected_revision: 3 },
      }],
      [COMMANDS.deleteEstimate, { id: create.id }],
      [COMMANDS.loadEstimateView],
      [COMMANDS.saveEstimateView, { state: { active_estimate_id: create.id } }],
    ]);
  });
});
