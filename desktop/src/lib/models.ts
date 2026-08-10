export const CATALOG_SORTS = [
  "price_asc",
  "price_desc",
  "name_asc",
  "product_id_asc",
] as const;

export type CatalogSort = (typeof CATALOG_SORTS)[number];

export const RELATION_CATEGORIES = [
  "selection",
  "additional",
  "construction",
] as const;

export type RelationCategory = (typeof RELATION_CATEGORIES)[number];

export interface ProductAttribute {
  name: string;
  value: string;
  unit?: string;
}

export interface CatalogProduct {
  product_id: string;
  name: string;
  spec: string;
  company_name: string;
  unit: string;
  price_won: number;
  contract_method: string;
  delivery_condition: string;
  delivery_days: string;
  contract_end_date: string;
  image_url: string;
  detail_url: string;
  g2b_url: string;
  attributes?: ProductAttribute[];
}

export interface CatalogRelation {
  parent_product_id: string;
  parent_name: string;
  relation_id: string;
  relation_kind: "additional" | "component";
  category: RelationCategory;
  product_id: string;
  name: string;
  spec: string;
  unit: string;
  price_won: number;
  company_name: string;
  detail_url: string;
  g2b_url: string;
  image_url: string;
}

export interface CatalogPage<T> {
  items: T[];
  page: number;
  page_count: number;
  total_count: number;
}

export interface ProductSearchRequest {
  company_name: string;
  query: string;
  sort: CatalogSort;
  page: number;
}

export interface RelationSearchRequest extends ProductSearchRequest {
  parent_product_id: string;
  category: RelationCategory;
}

export interface AddCatalogItemRequest {
  product_id: string;
  line_kind: "main" | "option";
  parent_product_id: string | null;
  relation_id: string | null;
}

export interface AddCatalogItemResult {
  estimate_id: string;
  line_count: number;
  revision: number;
}

export interface CatalogCacheStatus {
  state: "ready";
  contract_version: number;
  cache_version: number;
  release_identity: string;
  cache_key: string;
}

export interface CatalogViewState {
  query: string;
  sort: CatalogSort;
  page: number;
  selected_product_id: string | null;
  active_category: RelationCategory;
  product_scroll_top: number;
  relation_scroll_top: Record<RelationCategory, number>;
  relation_query: Record<RelationCategory, string>;
  relation_page: Record<RelationCategory, number>;
}

export type ComparisonSlot = "A" | "B" | "C";

export interface EstimateComparison {
  estimate_line_id: string;
  slot: ComparisonSlot;
  product_id: string;
  relation_id: string | null;
  company_snapshot: string;
  spec_snapshot: string;
  price_won_snapshot: number;
  g2b_url: string;
}

export interface EstimateLineInput {
  id: string;
  line_kind: "main" | "option";
  product_id: string;
  parent_product_id: string | null;
  relation_id: string | null;
  offer_operation: string | null;
  offer_key: string | null;
  item_name_snapshot: string;
  spec_snapshot: string;
  company_snapshot: string;
  unit_snapshot: string;
  unit_price_won_snapshot: number;
  quantity: string;
}

export interface EstimateLine extends EstimateLineInput {
  line_no: number;
  comparisons: EstimateComparison[];
}

export interface EstimateDocument {
  id: string;
  title: string;
  template_sha256: string;
  revision: number;
  created_at: string;
  updated_at: string;
  lines: EstimateLine[];
}

export interface EstimateSummary {
  id: string;
  title: string;
  revision: number;
  line_count: number;
  total_won: number;
  updated_at: string;
}

export interface CreateEstimateRequest {
  id: string;
  title: string;
  template_sha256: string;
  lines: EstimateLineInput[];
  comparisons: EstimateComparison[];
}

export interface RefreshEstimateComparisonsRequest {
  expected_revision: number;
}

export interface UpdateEstimateRequest {
  expected_revision: number;
  title: string;
  lines: EstimateLineInput[];
  comparisons: EstimateComparison[];
}

export interface EstimateViewState {
  active_estimate_id: string | null;
}

export interface DataStatus {
  company_count: number;
  product_count: number;
  relation_count: number;
  option_row_count: number;
  unique_option_count: number;
  pending_api_target_count: number;
  pending_site_product_count: number;
  ready: boolean;
  readiness: string;
  error: string | null;
}

export type DataSyncStage =
  | "sync"
  | "import-relations"
  | "materialize"
  | "rebuild-index"
  | "precompute";

export interface DataSyncStatus {
  state: "running" | "complete" | "failed";
  stage: DataSyncStage | null;
  error: string | null;
}

export interface DataDiagnosticResult {
  state: "passed" | "warning" | "failed";
  checked_at: string;
  code: string | null;
}

export interface WorkbookExportResult {
  path: string;
  file_name: string;
}

export interface ClipboardCopyResult {
  row_count: number;
}

export type DesktopRouteName = "catalog" | "estimates" | "estimate" | "data";

export interface DesktopViewState {
  route: DesktopRouteName;
  path: string;
}

export type ReconciliationState =
  | "idle"
  | "offline"
  | "queued"
  | "replaying"
  | "conflict";

export interface ReconciliationConflict {
  sequence: number;
  entity_id: string;
  reason_code: string;
}

export interface ReconciliationStatus {
  state: ReconciliationState;
  online: boolean;
  queued_count: number;
  conflicts: ReconciliationConflict[];
}

export type ConflictResolution = "keep-local" | "use-remote";

export interface ResolveConflictRequest {
  sequence: number;
  resolution: ConflictResolution;
}
