CREATE TABLE priority_product_description_observations (
    id INTEGER PRIMARY KEY,
    product_id TEXT NOT NULL
        REFERENCES priority_products(product_id) ON DELETE CASCADE,
    contract_item_management_number TEXT NOT NULL,
    page_url TEXT NOT NULL,
    endpoint_url TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL CHECK (length(request_fingerprint) = 64),
    response_body_sha256 TEXT REFERENCES raw_blobs(body_sha),
    outcome TEXT NOT NULL CHECK (outcome IN ('stored', 'missing', 'failed')),
    detail_html_sha256 TEXT,
    decoded_html TEXT,
    detail_text TEXT,
    parser_version INTEGER NOT NULL CHECK (parser_version > 0),
    http_status INTEGER,
    error_code TEXT CHECK (error_code IS NULL OR length(error_code) <= 64),
    observed_at TEXT NOT NULL,
    CHECK (
        (
            outcome = 'stored'
            AND response_body_sha256 IS NOT NULL
            AND detail_html_sha256 IS NOT NULL
            AND decoded_html IS NOT NULL
            AND detail_text IS NOT NULL
            AND error_code IS NULL
        )
        OR (
            outcome = 'missing'
            AND response_body_sha256 IS NOT NULL
            AND detail_html_sha256 IS NULL
            AND decoded_html IS NULL
            AND detail_text IS NULL
            AND error_code IS NULL
        )
        OR (
            outcome = 'failed'
            AND detail_html_sha256 IS NULL
            AND decoded_html IS NULL
            AND detail_text IS NULL
            AND error_code IS NOT NULL
        )
    )
);

CREATE TABLE priority_product_description_state (
    product_id TEXT PRIMARY KEY
        REFERENCES priority_products(product_id) ON DELETE CASCADE,
    latest_observation_id INTEGER NOT NULL UNIQUE
        REFERENCES priority_product_description_observations(id)
);

CREATE INDEX priority_product_description_outcome_idx
ON priority_product_description_observations(outcome, product_id);

CREATE TRIGGER priority_product_description_observations_no_update
BEFORE UPDATE ON priority_product_description_observations
BEGIN
    SELECT RAISE(ABORT, 'product description observations are immutable');
END;

CREATE TRIGGER priority_product_description_observations_no_delete
BEFORE DELETE ON priority_product_description_observations
BEGIN
    SELECT RAISE(ABORT, 'product description observations are immutable');
END;

CREATE TRIGGER priority_product_description_state_same_product_insert
BEFORE INSERT ON priority_product_description_state
WHEN NOT EXISTS (
    SELECT 1 FROM priority_product_description_observations
    WHERE id = NEW.latest_observation_id AND product_id = NEW.product_id
)
BEGIN
    SELECT RAISE(ABORT, 'product description state product mismatch');
END;

CREATE TRIGGER priority_product_description_state_same_product_update
BEFORE UPDATE ON priority_product_description_state
WHEN NOT EXISTS (
    SELECT 1 FROM priority_product_description_observations
    WHERE id = NEW.latest_observation_id AND product_id = NEW.product_id
)
BEGIN
    SELECT RAISE(ABORT, 'product description state product mismatch');
END;
