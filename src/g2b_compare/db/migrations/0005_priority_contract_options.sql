CREATE TABLE IF NOT EXISTS priority_product_contract_groups (
    product_id TEXT PRIMARY KEY,
    contract_group TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS priority_product_contract_group
ON priority_product_contract_groups(contract_group, product_id);

CREATE TABLE IF NOT EXISTS priority_contract_options (
    contract_group TEXT NOT NULL,
    relation_id TEXT PRIMARY KEY,
    option_product_id TEXT NOT NULL CHECK (length(option_product_id) = 8),
    relation_kind TEXT NOT NULL CHECK (relation_kind IN ('additional', 'component')),
    position INTEGER NOT NULL CHECK (position >= 0),
    company_name TEXT NOT NULL,
    raw_label TEXT NOT NULL,
    relation_price_won INTEGER NOT NULL DEFAULT 0 CHECK (relation_price_won >= 0),
    observed_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    UNIQUE (contract_group, relation_kind, position)
);

CREATE INDEX IF NOT EXISTS priority_contract_options_group
ON priority_contract_options(contract_group, active, position);

CREATE INDEX IF NOT EXISTS priority_contract_options_child
ON priority_contract_options(option_product_id, active);
