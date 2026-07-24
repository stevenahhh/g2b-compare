CREATE TABLE priority_product_offers (
    operation TEXT NOT NULL,
    offer_key TEXT NOT NULL,
    product_id TEXT NOT NULL,
    company_name TEXT NOT NULL DEFAULT '',
    price_won INTEGER NOT NULL DEFAULT 0 CHECK (price_won >= 0),
    unit TEXT NOT NULL DEFAULT '',
    contract_method TEXT NOT NULL DEFAULT '',
    delivery_condition TEXT NOT NULL DEFAULT '',
    delivery_days TEXT NOT NULL DEFAULT '',
    contract_end_date TEXT NOT NULL DEFAULT '',
    image_url TEXT NOT NULL DEFAULT '',
    detail_url TEXT NOT NULL DEFAULT '',
    raw_json TEXT NOT NULL DEFAULT '{}',
    observed_at TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    PRIMARY KEY (operation, offer_key)
);

CREATE INDEX priority_product_offers_product
ON priority_product_offers(product_id, active, contract_end_date);

CREATE TABLE priority_product_attributes (
    product_id TEXT NOT NULL,
    attribute_key TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    raw_name TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    canonical_value TEXT NOT NULL DEFAULT '',
    canonical_unit TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL,
    PRIMARY KEY (product_id, attribute_key, ordinal)
);

CREATE TABLE verified_product_options (
    relation_id TEXT PRIMARY KEY,
    parent_operation TEXT NOT NULL,
    parent_offer_key TEXT NOT NULL,
    parent_product_id TEXT NOT NULL CHECK (length(parent_product_id) = 8),
    option_product_id TEXT NOT NULL CHECK (length(option_product_id) = 8),
    relation_kind TEXT NOT NULL CHECK (relation_kind IN ('additional', 'component')),
    position INTEGER NOT NULL CHECK (position >= 0),
    company_name TEXT NOT NULL,
    raw_label TEXT NOT NULL,
    relation_price_won INTEGER NOT NULL DEFAULT 0 CHECK (relation_price_won >= 0),
    detail_url TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    CHECK (parent_product_id <> option_product_id),
    UNIQUE (parent_operation, parent_offer_key, relation_kind, position)
);

CREATE INDEX verified_product_options_parent
ON verified_product_options(parent_product_id, active, position);

CREATE VIRTUAL TABLE priority_product_search USING fts5(
    product_id UNINDEXED,
    search_text,
    tokenize = 'unicode61'
);

CREATE TABLE estimate_drafts (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    template_sha256 TEXT NOT NULL CHECK (length(template_sha256) = 64),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE estimate_lines (
    id TEXT PRIMARY KEY,
    estimate_id TEXT NOT NULL,
    line_no INTEGER NOT NULL CHECK (line_no BETWEEN 1 AND 9),
    line_kind TEXT NOT NULL CHECK (line_kind IN ('main', 'option')),
    product_id TEXT NOT NULL CHECK (length(product_id) = 8),
    parent_product_id TEXT,
    relation_id TEXT,
    offer_operation TEXT,
    offer_key TEXT,
    item_name_snapshot TEXT NOT NULL,
    spec_snapshot TEXT NOT NULL,
    company_snapshot TEXT NOT NULL,
    unit_snapshot TEXT NOT NULL,
    unit_price_won_snapshot INTEGER NOT NULL CHECK (unit_price_won_snapshot >= 0),
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    FOREIGN KEY (estimate_id) REFERENCES estimate_drafts(id) ON DELETE CASCADE,
    UNIQUE (estimate_id, line_no),
    CHECK (
        (line_kind = 'main' AND parent_product_id IS NULL AND relation_id IS NULL)
        OR
        (line_kind = 'option' AND parent_product_id IS NOT NULL AND relation_id IS NOT NULL)
    )
);

CREATE TABLE estimate_comparisons (
    estimate_line_id TEXT NOT NULL,
    slot TEXT NOT NULL CHECK (slot IN ('A', 'B', 'C')),
    product_id TEXT NOT NULL CHECK (length(product_id) = 8),
    relation_id TEXT,
    company_snapshot TEXT NOT NULL,
    spec_snapshot TEXT NOT NULL,
    price_won_snapshot INTEGER NOT NULL CHECK (price_won_snapshot >= 0),
    PRIMARY KEY (estimate_line_id, slot),
    FOREIGN KEY (estimate_line_id) REFERENCES estimate_lines(id) ON DELETE CASCADE
);
