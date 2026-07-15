CREATE TABLE IF NOT EXISTS source_snapshots (
    id INTEGER PRIMARY KEY,
    operation TEXT NOT NULL,
    parent_id INTEGER REFERENCES source_snapshots(id),
    mode TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    completeness TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('building', 'complete', 'failed')),
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS active_source_snapshots (
    operation TEXT PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES source_snapshots(id)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY,
    operation TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    cursor_json TEXT NOT NULL,
    page_size INTEGER NOT NULL CHECK (page_size > 0),
    calls INTEGER NOT NULL DEFAULT 0 CHECK (calls >= 0),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error_kind TEXT
);

CREATE TABLE IF NOT EXISTS sync_windows (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES sync_runs(id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    UNIQUE (run_id, ordinal)
);

CREATE TABLE IF NOT EXISTS request_manifests (
    id INTEGER PRIMARY KEY,
    operation TEXT NOT NULL,
    method TEXT NOT NULL,
    official_path TEXT NOT NULL,
    params_json_without_key TEXT NOT NULL,
    params_sha TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE (operation, params_sha)
);

CREATE TABLE IF NOT EXISTS raw_blobs (
    body_sha TEXT PRIMARY KEY,
    raw_path TEXT NOT NULL UNIQUE,
    content_type TEXT NOT NULL,
    byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_pages (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES sync_runs(id),
    window_id INTEGER NOT NULL REFERENCES sync_windows(id),
    page_no INTEGER NOT NULL CHECK (page_no > 0),
    request_manifest_id INTEGER NOT NULL REFERENCES request_manifests(id),
    body_sha TEXT NOT NULL REFERENCES raw_blobs(body_sha),
    item_count INTEGER NOT NULL CHECK (item_count >= 0),
    total_count INTEGER NOT NULL CHECK (total_count >= 0),
    status_code INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    UNIQUE (run_id, window_id, page_no)
);

CREATE TABLE IF NOT EXISTS source_records (
    source_snapshot_id INTEGER NOT NULL REFERENCES source_snapshots(id),
    operation TEXT NOT NULL,
    source_record_key TEXT NOT NULL,
    product_id TEXT NOT NULL,
    origin_page_id INTEGER NOT NULL REFERENCES sync_pages(id),
    raw_fields_json TEXT NOT NULL,
    payload_sha TEXT NOT NULL,
    canonical_record_sha TEXT NOT NULL,
    is_tombstone INTEGER NOT NULL CHECK (is_tombstone IN (0, 1)),
    PRIMARY KEY (source_snapshot_id, operation, source_record_key)
);

CREATE TABLE IF NOT EXISTS catalog_generations (
    id INTEGER PRIMARY KEY,
    catalog_source_sha TEXT NOT NULL UNIQUE,
    five_source_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_source_fingerprints (
    catalog_generation_id INTEGER NOT NULL REFERENCES catalog_generations(id),
    product_id TEXT NOT NULL,
    fingerprint_sha TEXT NOT NULL,
    PRIMARY KEY (catalog_generation_id, product_id)
);

CREATE TABLE IF NOT EXISTS attribute_snapshots (
    id INTEGER PRIMARY KEY,
    catalog_generation_id INTEGER NOT NULL REFERENCES catalog_generations(id),
    parent_id INTEGER REFERENCES attribute_snapshots(id),
    complete_product_count INTEGER NOT NULL CHECK (complete_product_count >= 0),
    active_product_count INTEGER NOT NULL CHECK (active_product_count >= 0),
    status TEXT NOT NULL CHECK (status IN ('building', 'complete', 'failed')),
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS active_attribute_snapshots (
    catalog_generation_id INTEGER PRIMARY KEY REFERENCES catalog_generations(id),
    snapshot_id INTEGER NOT NULL REFERENCES attribute_snapshots(id)
);

CREATE TABLE IF NOT EXISTS attribute_product_states (
    attribute_snapshot_id INTEGER NOT NULL REFERENCES attribute_snapshots(id),
    product_id TEXT NOT NULL,
    fetch_status TEXT NOT NULL CHECK (fetch_status IN (
        'complete-nonempty', 'complete-empty', 'pending', 'failed',
        'expired-retained', 'carried-forward'
    )),
    source_fingerprint_sha TEXT NOT NULL,
    completed_at TEXT,
    origin_snapshot_id INTEGER REFERENCES attribute_snapshots(id),
    PRIMARY KEY (attribute_snapshot_id, product_id)
);

CREATE TABLE IF NOT EXISTS attribute_records (
    attribute_snapshot_id INTEGER NOT NULL REFERENCES attribute_snapshots(id),
    product_id TEXT NOT NULL,
    attribute_source_key TEXT NOT NULL,
    origin_page_id INTEGER NOT NULL REFERENCES sync_pages(id),
    raw_fields_json TEXT NOT NULL,
    payload_sha TEXT NOT NULL,
    PRIMARY KEY (attribute_snapshot_id, product_id, attribute_source_key)
);

CREATE TABLE IF NOT EXISTS normalization_versions (
    id INTEGER PRIMARY KEY,
    version TEXT NOT NULL UNIQUE,
    manifest_sha TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS index_versions (
    id INTEGER PRIMARY KEY,
    materialization_id INTEGER NOT NULL,
    index_artifact_sha TEXT NOT NULL,
    index_manifest_sha TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('building', 'complete', 'failed')),
    created_at TEXT NOT NULL,
    UNIQUE (materialization_id, index_artifact_sha, index_manifest_sha)
);

CREATE TABLE IF NOT EXISTS relation_snapshots (
    id INTEGER PRIMARY KEY,
    source_manifest_sha TEXT NOT NULL UNIQUE,
    relation_content_sha TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('building', 'complete', 'failed')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS curated_relations (
    relation_snapshot_id INTEGER NOT NULL REFERENCES relation_snapshots(id),
    id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    child_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_sha TEXT NOT NULL,
    sheet_name TEXT NOT NULL,
    row_no INTEGER NOT NULL CHECK (row_no > 0),
    PRIMARY KEY (relation_snapshot_id, id),
    UNIQUE (
        relation_snapshot_id, parent_id, child_id, source_type,
        source_sha, sheet_name, row_no
    )
);

CREATE TABLE IF NOT EXISTS materialization_snapshots (
    id INTEGER PRIMARY KEY,
    catalog_generation_id INTEGER NOT NULL REFERENCES catalog_generations(id),
    attribute_snapshot_id INTEGER NOT NULL REFERENCES attribute_snapshots(id),
    materialization_source_sha TEXT NOT NULL,
    normalization_version TEXT NOT NULL,
    materialization_policy_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('building', 'complete', 'failed')),
    attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
    heartbeat_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (
        materialization_source_sha, normalization_version,
        materialization_policy_version
    )
);

CREATE TABLE IF NOT EXISTS products (
    materialization_id INTEGER NOT NULL REFERENCES materialization_snapshots(id),
    product_id TEXT NOT NULL,
    category_no TEXT NOT NULL,
    detail_category_no TEXT NOT NULL,
    product_name_raw TEXT NOT NULL,
    product_name_key TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    data_as_of TEXT NOT NULL,
    PRIMARY KEY (materialization_id, product_id)
);

CREATE TABLE IF NOT EXISTS catalog_offers (
    materialization_id INTEGER NOT NULL,
    operation TEXT NOT NULL,
    offer_key TEXT NOT NULL,
    product_id TEXT NOT NULL,
    contract_price_won INTEGER CHECK (contract_price_won >= 0),
    unit_raw TEXT,
    unit_key TEXT,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    source_updated_at TEXT NOT NULL,
    PRIMARY KEY (materialization_id, operation, offer_key),
    FOREIGN KEY (materialization_id, product_id)
        REFERENCES products(materialization_id, product_id)
);

CREATE TABLE IF NOT EXISTS product_attributes (
    materialization_id INTEGER NOT NULL,
    product_id TEXT NOT NULL,
    attribute_key TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    attribute_snapshot_id INTEGER NOT NULL REFERENCES attribute_snapshots(id),
    attribute_source_key TEXT NOT NULL,
    raw_name TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    canonical_value TEXT,
    canonical_unit TEXT,
    parse_status TEXT NOT NULL,
    PRIMARY KEY (materialization_id, product_id, attribute_key, ordinal),
    FOREIGN KEY (materialization_id, product_id)
        REFERENCES products(materialization_id, product_id)
);

CREATE TABLE IF NOT EXISTS option_role_observations (
    materialization_id INTEGER NOT NULL REFERENCES materialization_snapshots(id),
    source_snapshot_id INTEGER NOT NULL REFERENCES source_snapshots(id),
    source_row_key TEXT NOT NULL,
    product_id TEXT NOT NULL,
    delivery_request_key TEXT NOT NULL,
    item_sequence INTEGER NOT NULL,
    change_sequence INTEGER NOT NULL,
    role_raw TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (materialization_id, source_snapshot_id, source_row_key)
);

CREATE TABLE IF NOT EXISTS release_bundles (
    id INTEGER PRIMARY KEY,
    materialization_id INTEGER NOT NULL REFERENCES materialization_snapshots(id),
    index_version_id INTEGER NOT NULL REFERENCES index_versions(id),
    relation_snapshot_id INTEGER NOT NULL REFERENCES relation_snapshots(id),
    ranking_version TEXT NOT NULL,
    expected_cache_rows INTEGER NOT NULL CHECK (expected_cache_rows >= 0),
    written_cache_rows INTEGER NOT NULL CHECK (written_cache_rows >= 0),
    cache_content_sha TEXT,
    release_bundle_sha TEXT UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('building', 'ready', 'failed')),
    attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
    ready_attempt_no INTEGER,
    heartbeat_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (
        materialization_id, index_version_id,
        relation_snapshot_id, ranking_version
    )
);

CREATE TABLE IF NOT EXISTS active_release (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    bundle_id INTEGER NOT NULL REFERENCES release_bundles(id)
);

CREATE VIEW IF NOT EXISTS active_materialization AS
SELECT materialization_snapshots.*
FROM active_release
JOIN release_bundles ON release_bundles.id = active_release.bundle_id
JOIN materialization_snapshots
    ON materialization_snapshots.id = release_bundles.materialization_id
WHERE release_bundles.status = 'ready'
  AND release_bundles.expected_cache_rows = release_bundles.written_cache_rows
  AND release_bundles.cache_content_sha IS NOT NULL
  AND release_bundles.release_bundle_sha IS NOT NULL
  AND release_bundles.ready_attempt_no = release_bundles.attempt_no
  AND (
      SELECT COUNT(*)
      FROM comparator_cache
      WHERE comparator_cache.release_bundle_id = release_bundles.id
        AND comparator_cache.attempt_no = release_bundles.attempt_no
  ) = release_bundles.written_cache_rows;

CREATE TABLE IF NOT EXISTS comparator_cache (
    release_bundle_id INTEGER NOT NULL REFERENCES release_bundles(id),
    attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
    anchor_id TEXT NOT NULL,
    slot INTEGER NOT NULL CHECK (slot BETWEEN 1 AND 3),
    payload_json TEXT NOT NULL,
    payload_sha TEXT NOT NULL,
    PRIMARY KEY (release_bundle_id, attempt_no, anchor_id, slot)
);

CREATE TRIGGER IF NOT EXISTS guard_active_release_insert
BEFORE INSERT ON active_release
WHEN NOT EXISTS (
    SELECT 1
    FROM release_bundles
    WHERE release_bundles.id = NEW.bundle_id
      AND release_bundles.status = 'ready'
      AND release_bundles.expected_cache_rows = release_bundles.written_cache_rows
      AND release_bundles.cache_content_sha IS NOT NULL
      AND release_bundles.release_bundle_sha IS NOT NULL
      AND release_bundles.ready_attempt_no = release_bundles.attempt_no
      AND (
          SELECT COUNT(*)
          FROM comparator_cache
          WHERE comparator_cache.release_bundle_id = release_bundles.id
            AND comparator_cache.attempt_no = release_bundles.attempt_no
      ) = release_bundles.written_cache_rows
)
BEGIN
    SELECT RAISE(ABORT, 'release bundle is not ready');
END;

CREATE TRIGGER IF NOT EXISTS guard_active_release_update
BEFORE UPDATE OF bundle_id ON active_release
WHEN NOT EXISTS (
    SELECT 1
    FROM release_bundles
    WHERE release_bundles.id = NEW.bundle_id
      AND release_bundles.status = 'ready'
      AND release_bundles.expected_cache_rows = release_bundles.written_cache_rows
      AND release_bundles.cache_content_sha IS NOT NULL
      AND release_bundles.release_bundle_sha IS NOT NULL
      AND release_bundles.ready_attempt_no = release_bundles.attempt_no
      AND (
          SELECT COUNT(*)
          FROM comparator_cache
          WHERE comparator_cache.release_bundle_id = release_bundles.id
            AND comparator_cache.attempt_no = release_bundles.attempt_no
      ) = release_bundles.written_cache_rows
)
BEGIN
    SELECT RAISE(ABORT, 'release bundle is not ready');
END;

CREATE TABLE IF NOT EXISTS attribute_enrichment_queue (
    catalog_generation_id INTEGER NOT NULL REFERENCES catalog_generations(id),
    product_id TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL,
    attempts INTEGER NOT NULL CHECK (attempts >= 0),
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    PRIMARY KEY (catalog_generation_id, product_id)
);

CREATE TABLE IF NOT EXISTS api_call_ledger (
    id INTEGER PRIMARY KEY,
    operation TEXT NOT NULL,
    attempted_at_utc TEXT NOT NULL,
    kst_date TEXT NOT NULL,
    status_code INTEGER,
    reservation_state TEXT NOT NULL CHECK (
        reservation_state IN ('reserved', 'succeeded', 'failed')
    )
);

CREATE INDEX IF NOT EXISTS idx_source_records_product
    ON source_records(source_snapshot_id, product_id);
CREATE INDEX IF NOT EXISTS idx_attribute_records_product
    ON attribute_records(attribute_snapshot_id, product_id);
CREATE INDEX IF NOT EXISTS idx_products_search
    ON products(materialization_id, active, category_no, detail_category_no, product_name_key);
CREATE INDEX IF NOT EXISTS idx_products_id
    ON products(product_id);
CREATE INDEX IF NOT EXISTS idx_catalog_offers_product_unit
    ON catalog_offers(materialization_id, product_id, unit_key);
CREATE INDEX IF NOT EXISTS idx_attribute_queue_state
    ON attribute_enrichment_queue(catalog_generation_id, status, priority);
CREATE INDEX IF NOT EXISTS idx_option_roles_product
    ON option_role_observations(materialization_id, product_id);
CREATE INDEX IF NOT EXISTS idx_api_call_rolling
    ON api_call_ledger(operation, attempted_at_utc);
