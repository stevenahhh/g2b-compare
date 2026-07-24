"""SQLite schema for priority collection data."""

from typing import Final

SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS priority_companies (
    name TEXT PRIMARY KEY,
    source_row INTEGER NOT NULL,
    location TEXT NOT NULL,
    company_type TEXT NOT NULL,
    declared_product_count INTEGER NOT NULL,
    contract_end_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS priority_options (
    source_row INTEGER PRIMARY KEY,
    company_name TEXT NOT NULL,
    option_kind TEXT NOT NULL,
    product_id TEXT NOT NULL,
    item_name TEXT NOT NULL,
    spec TEXT NOT NULL,
    price_won INTEGER NOT NULL,
    details TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS priority_options_product
ON priority_options(company_name, product_id);
CREATE TABLE IF NOT EXISTS priority_products (
    product_id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    contract_number TEXT NOT NULL,
    contract_sequence TEXT NOT NULL,
    category_number TEXT NOT NULL,
    category_name TEXT NOT NULL,
    detail_category_number TEXT NOT NULL,
    spec TEXT NOT NULL,
    company_name TEXT NOT NULL,
    unit TEXT NOT NULL,
    price_won INTEGER NOT NULL,
    contract_method TEXT NOT NULL,
    delivery_condition TEXT NOT NULL,
    delivery_days TEXT NOT NULL,
    contract_end_date TEXT NOT NULL,
    image_url TEXT NOT NULL,
    detail_url TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    site_status TEXT NOT NULL DEFAULT '',
    site_crawled_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS priority_products_company
ON priority_products(company_name, product_id);
CREATE TABLE IF NOT EXISTS priority_product_options (
    parent_product_id TEXT NOT NULL,
    option_product_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    raw_label TEXT NOT NULL,
    price_won INTEGER NOT NULL,
    PRIMARY KEY (parent_product_id, option_product_id)
);
CREATE TABLE IF NOT EXISTS priority_product_contract_groups (
    product_id TEXT PRIMARY KEY,
    contract_group TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS priority_product_contract_group
ON priority_product_contract_groups(contract_group, product_id);
CREATE TABLE IF NOT EXISTS priority_contract_options (
    contract_group TEXT NOT NULL,
    relation_id TEXT PRIMARY KEY,
    option_product_id TEXT NOT NULL,
    relation_kind TEXT NOT NULL,
    position INTEGER NOT NULL,
    company_name TEXT NOT NULL,
    raw_label TEXT NOT NULL,
    relation_price_won INTEGER NOT NULL,
    observed_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (contract_group, relation_kind, position)
);
CREATE INDEX IF NOT EXISTS priority_contract_options_group
ON priority_contract_options(contract_group, active, position);
CREATE INDEX IF NOT EXISTS priority_contract_options_child
ON priority_contract_options(option_product_id, active);
CREATE TABLE IF NOT EXISTS priority_crawl_state (
    company_name TEXT NOT NULL,
    operation TEXT NOT NULL,
    next_page INTEGER NOT NULL,
    complete INTEGER NOT NULL,
    PRIMARY KEY (company_name, operation)
);
CREATE TABLE IF NOT EXISTS priority_company_crawl_pages (
    company_name TEXT NOT NULL,
    operation TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    page_size INTEGER NOT NULL,
    provider_total_count INTEGER NOT NULL,
    accepted_count INTEGER NOT NULL,
    quarantined_count INTEGER NOT NULL,
    request_fingerprint TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (company_name, operation, page_number)
);
CREATE TABLE IF NOT EXISTS priority_company_quarantine (
    company_name TEXT NOT NULL,
    operation TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    row_number INTEGER NOT NULL,
    reason TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (company_name, operation, page_number, row_number)
);
"""

UPSERT_PRODUCT: Final = """
INSERT INTO priority_products VALUES (
    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ''
) ON CONFLICT(product_id) DO UPDATE SET
    operation=excluded.operation,
    contract_number=excluded.contract_number,
    contract_sequence=excluded.contract_sequence,
    category_number=excluded.category_number,
    category_name=excluded.category_name,
    detail_category_number=excluded.detail_category_number,
    spec=excluded.spec,
    company_name=excluded.company_name,
    unit=excluded.unit,
    price_won=excluded.price_won,
    contract_method=excluded.contract_method,
    delivery_condition=excluded.delivery_condition,
    delivery_days=excluded.delivery_days,
    contract_end_date=excluded.contract_end_date,
    image_url=excluded.image_url,
    detail_url=excluded.detail_url,
    raw_json=excluded.raw_json,
    observed_at=excluded.observed_at
"""

UPSERT_CRAWL_STATE: Final = """
INSERT INTO priority_crawl_state VALUES (?, ?, ?, ?)
ON CONFLICT(company_name, operation) DO UPDATE SET
    next_page=excluded.next_page, complete=excluded.complete
"""

SELECT_PENDING_SITE: Final = """
SELECT product_id FROM priority_products
WHERE site_crawled_at = '' ORDER BY product_id
"""

SELECT_PENDING_SITE_LIMIT: Final = SELECT_PENDING_SITE + " LIMIT ?"

UPDATE_SITE_RESULT: Final = """
UPDATE priority_products SET site_status = ?, site_crawled_at = ?
WHERE product_id = ?
"""
