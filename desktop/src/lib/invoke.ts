import { invoke as tauriInvoke } from "@tauri-apps/api/core";

import type {
  AddCatalogItemRequest,
  AddCatalogItemResult,
  CatalogCacheStatus,
  CatalogPage,
  CatalogProduct,
  CatalogRelation,
  CatalogViewState,
  ClipboardCopyResult,
  CreateEstimateRequest,
  DataDiagnosticResult,
  DataStatus,
  DataSyncStatus,
  DesktopViewState,
  EstimateDocument,
  EstimateSummary,
  EstimateViewState,
  ProductSearchRequest,
  ReconciliationStatus,
  RefreshEstimateComparisonsRequest,
  RelationSearchRequest,
  ResolveConflictRequest,
  UpdateEstimateRequest,
  WorkbookExportResult,
} from "./models";

export const COMMANDS = {
  searchProducts: "search_products",
  searchRelations: "search_relations",
  addCatalogItem: "add_catalog_item",
  openProduct: "open_product",
  loadCatalogView: "load_catalog_view",
  saveCatalogView: "save_catalog_view",
  getCatalogCacheStatus: "get_catalog_cache_status",
  listEstimates: "list_estimates",
  createEstimate: "create_estimate",
  readEstimate: "read_estimate",
  updateEstimate: "update_estimate",
  refreshEstimateComparisons: "refresh_estimate_comparisons",
  deleteEstimate: "delete_estimate",
  loadEstimateView: "load_estimate_view",
  saveEstimateView: "save_estimate_view",
  getDataStatus: "get_data_status",
  runDataSync: "run_data_sync",
  runDataDiagnostics: "run_data_diagnostics",
  exportEstimateWorkbook: "export_estimate_workbook",
  copyEstimateTable: "copy_estimate_table",
  loadDesktopView: "load_desktop_view",
  saveDesktopView: "save_desktop_view",
  getReconciliationStatus: "get_reconciliation_status",
  replayPendingChanges: "replay_pending_changes",
  resolveReconciliationConflict: "resolve_reconciliation_conflict",
} as const;

export type InvokeImplementation = <T>(
  command: string,
  args?: Record<string, unknown>,
) => Promise<T>;

export interface CatalogClient {
  searchProducts(request: ProductSearchRequest): Promise<CatalogPage<CatalogProduct>>;
  searchRelations(request: RelationSearchRequest): Promise<CatalogPage<CatalogRelation>>;
  addItem(request: AddCatalogItemRequest): Promise<AddCatalogItemResult>;
  openProduct(detailUrl: string): Promise<void>;
  loadView(): Promise<CatalogViewState | null>;
  saveView(state: CatalogViewState): Promise<void>;
  getCacheStatus(): Promise<CatalogCacheStatus>;
}

export function createCatalogClient(
  invokeImplementation: InvokeImplementation = tauriInvoke,
): CatalogClient {
  return {
    searchProducts: (request) =>
      invokeImplementation<CatalogPage<CatalogProduct>>(COMMANDS.searchProducts, {
        request,
      }),
    searchRelations: (request) =>
      invokeImplementation<CatalogPage<CatalogRelation>>(COMMANDS.searchRelations, {
        request,
      }),
    addItem: (request) =>
      invokeImplementation<AddCatalogItemResult>(COMMANDS.addCatalogItem, {
        request,
      }),
    openProduct: (detailUrl) =>
      invokeImplementation<void>(COMMANDS.openProduct, { detailUrl }),
    loadView: () =>
      invokeImplementation<CatalogViewState | null>(COMMANDS.loadCatalogView),
    saveView: (state) =>
      invokeImplementation<void>(COMMANDS.saveCatalogView, { state }),
    getCacheStatus: () =>
      invokeImplementation<CatalogCacheStatus>(COMMANDS.getCatalogCacheStatus),
  };
}

export interface EstimateClient {
  listEstimates(): Promise<EstimateSummary[]>;
  createEstimate(request: CreateEstimateRequest): Promise<EstimateDocument>;
  readEstimate(id: string): Promise<EstimateDocument>;
  updateEstimate(id: string, request: UpdateEstimateRequest): Promise<EstimateDocument>;
  refreshEstimateComparisons(
    id: string,
    request: RefreshEstimateComparisonsRequest,
  ): Promise<EstimateDocument>;
  deleteEstimate(id: string): Promise<void>;
  loadEstimateView(): Promise<EstimateViewState | null>;
  saveEstimateView(state: EstimateViewState): Promise<void>;
}

export function createEstimateClient(
  invokeImplementation: InvokeImplementation = tauriInvoke,
): EstimateClient {
  return {
    listEstimates: () =>
      invokeImplementation<EstimateSummary[]>(COMMANDS.listEstimates),
    createEstimate: (request) =>
      invokeImplementation<EstimateDocument>(COMMANDS.createEstimate, { request }),
    readEstimate: (id) =>
      invokeImplementation<EstimateDocument>(COMMANDS.readEstimate, { id }),
    updateEstimate: (id, request) =>
      invokeImplementation<EstimateDocument>(COMMANDS.updateEstimate, { id, request }),
    refreshEstimateComparisons: (id, request) =>
      invokeImplementation<EstimateDocument>(COMMANDS.refreshEstimateComparisons, { id, request }),
    deleteEstimate: (id) =>
      invokeImplementation<void>(COMMANDS.deleteEstimate, { id }),
    loadEstimateView: () =>
      invokeImplementation<EstimateViewState | null>(COMMANDS.loadEstimateView),
    saveEstimateView: (state) =>
      invokeImplementation<void>(COMMANDS.saveEstimateView, { state }),
  };
}

export interface DataClient {
  getDataStatus(): Promise<DataStatus>;
  runDataSync(): Promise<DataSyncStatus>;
  runDataDiagnostics(): Promise<DataDiagnosticResult>;
}

export function createDataClient(
  invokeImplementation: InvokeImplementation = tauriInvoke,
): DataClient {
  return {
    getDataStatus: () =>
      invokeImplementation<DataStatus>(COMMANDS.getDataStatus),
    runDataSync: () =>
      invokeImplementation<DataSyncStatus>(COMMANDS.runDataSync),
    runDataDiagnostics: () =>
      invokeImplementation<DataDiagnosticResult>(COMMANDS.runDataDiagnostics),
  };
}

export interface DocumentActionClient {
  exportEstimateWorkbook(id: string): Promise<WorkbookExportResult>;
  copyEstimateTable(id: string): Promise<ClipboardCopyResult>;
}

export function createDocumentActionClient(
  invokeImplementation: InvokeImplementation = tauriInvoke,
): DocumentActionClient {
  return {
    exportEstimateWorkbook: (id) =>
      invokeImplementation<WorkbookExportResult>(COMMANDS.exportEstimateWorkbook, { id }),
    copyEstimateTable: (id) =>
      invokeImplementation<ClipboardCopyResult>(COMMANDS.copyEstimateTable, { id }),
  };
}

export interface DesktopStateClient {
  loadDesktopView(): Promise<DesktopViewState | null>;
  saveDesktopView(state: DesktopViewState): Promise<void>;
  getReconciliationStatus(): Promise<ReconciliationStatus>;
  replayPendingChanges(): Promise<ReconciliationStatus>;
  resolveReconciliationConflict(request: ResolveConflictRequest): Promise<ReconciliationStatus>;
}

export function createDesktopStateClient(
  invokeImplementation: InvokeImplementation = tauriInvoke,
): DesktopStateClient {
  return {
    loadDesktopView: () =>
      invokeImplementation<DesktopViewState | null>(COMMANDS.loadDesktopView),
    saveDesktopView: (state) =>
      invokeImplementation<void>(COMMANDS.saveDesktopView, { state }),
    getReconciliationStatus: () =>
      invokeImplementation<ReconciliationStatus>(COMMANDS.getReconciliationStatus),
    replayPendingChanges: () =>
      invokeImplementation<ReconciliationStatus>(COMMANDS.replayPendingChanges),
    resolveReconciliationConflict: (request) =>
      invokeImplementation<ReconciliationStatus>(COMMANDS.resolveReconciliationConflict, { request }),
  };
}

export type DesktopClient = CatalogClient
  & EstimateClient
  & DataClient
  & DocumentActionClient
  & DesktopStateClient;

export const catalogClient = createCatalogClient();
export const estimateClient = createEstimateClient();
export const dataClient = createDataClient();
export const documentActionClient = createDocumentActionClient();
export const desktopStateClient = createDesktopStateClient();
export const desktopClient: DesktopClient = {
  ...catalogClient,
  ...estimateClient,
  ...dataClient,
  ...documentActionClient,
  ...desktopStateClient,
};
