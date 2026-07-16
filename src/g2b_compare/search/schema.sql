CREATE TABLE IF NOT EXISTS index_versions (
    id INTEGER PRIMARY KEY,
    materialization_id INTEGER NOT NULL,
    index_artifact_sha TEXT NOT NULL,
    index_manifest_sha TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('building', 'complete', 'failed')),
    created_at TEXT NOT NULL,
    UNIQUE (materialization_id, index_artifact_sha, index_manifest_sha)
);

CREATE TABLE IF NOT EXISTS search_membership (
    materialization_id INTEGER NOT NULL,
    product_id TEXT NOT NULL,
    category_no TEXT NOT NULL,
    detail_category_no TEXT NOT NULL,
    product_name_raw TEXT NOT NULL,
    product_name_key TEXT NOT NULL,
    option_text TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    PRIMARY KEY (materialization_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_search_exact_membership
ON search_membership(
    materialization_id, category_no, detail_category_no, product_name_key, active
);

CREATE TABLE IF NOT EXISTS search_index_members (
    materialization_id INTEGER NOT NULL,
    member_name TEXT NOT NULL,
    member_bytes BLOB NOT NULL,
    PRIMARY KEY (materialization_id, member_name)
);

CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
    materialization_id UNINDEXED,
    product_id UNINDEXED,
    product_name_key,
    product_name_raw,
    tokenize = 'unicode61'
);
