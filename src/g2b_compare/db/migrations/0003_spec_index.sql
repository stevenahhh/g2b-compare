ALTER TABLE catalog_offers ADD COLUMN contract_corp_id TEXT;
ALTER TABLE products ADD COLUMN spec_name TEXT NOT NULL DEFAULT '';
ALTER TABLE products ADD COLUMN detail TEXT NOT NULL DEFAULT '';
ALTER TABLE products ADD COLUMN characteristic TEXT NOT NULL DEFAULT '';
ALTER TABLE release_bundles
    ADD COLUMN slot_policy_version TEXT NOT NULL DEFAULT 'v1';

CREATE TABLE product_spec_index (
    materialization_id INTEGER NOT NULL,
    product_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('attr', 'spec', 'option')),
    attribute_key TEXT NOT NULL,
    dimension TEXT NOT NULL,
    relation TEXT NOT NULL CHECK (relation IN ('eq', 'le', 'ge', 'range')),
    value_low TEXT,
    value_high TEXT,
    canonical_unit TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (
        materialization_id, product_id, source_kind, attribute_key,
        dimension, ordinal
    ),
    FOREIGN KEY (materialization_id, product_id)
        REFERENCES products(materialization_id, product_id)
);

CREATE INDEX idx_spec_dim_value ON product_spec_index (
    materialization_id, dimension, value_low, value_high
);

CREATE TABLE category_parse_stats (
    materialization_id INTEGER NOT NULL,
    category_no TEXT NOT NULL,
    detail_category_no TEXT NOT NULL,
    product_count INTEGER NOT NULL CHECK (product_count >= 0),
    numeric_span_count INTEGER NOT NULL CHECK (numeric_span_count >= 0),
    parsed_semantic_count INTEGER NOT NULL CHECK (parsed_semantic_count >= 0),
    attribute_covered_count INTEGER NOT NULL CHECK (attribute_covered_count >= 0),
    PRIMARY KEY (materialization_id, category_no, detail_category_no)
);
