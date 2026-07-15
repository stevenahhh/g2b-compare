CREATE TABLE attribute_records_new (
    attribute_snapshot_id INTEGER NOT NULL REFERENCES attribute_snapshots(id),
    product_id TEXT NOT NULL,
    attribute_source_key TEXT NOT NULL,
    origin_page_id INTEGER NOT NULL REFERENCES sync_pages(id),
    raw_fields_json TEXT NOT NULL,
    payload_sha TEXT NOT NULL,
    PRIMARY KEY (attribute_snapshot_id, product_id, attribute_source_key),
    FOREIGN KEY (attribute_snapshot_id, product_id)
        REFERENCES attribute_product_states(attribute_snapshot_id, product_id)
        DEFERRABLE INITIALLY DEFERRED
);

INSERT INTO attribute_records_new
SELECT * FROM attribute_records;

DROP TABLE attribute_records;
ALTER TABLE attribute_records_new RENAME TO attribute_records;

CREATE INDEX idx_attribute_records_product
    ON attribute_records(attribute_snapshot_id, product_id);

DROP VIEW active_materialization;

CREATE VIEW active_materialization AS
SELECT materialization_snapshots.*
FROM active_release
JOIN release_bundles ON release_bundles.id = active_release.bundle_id
JOIN materialization_snapshots
    ON materialization_snapshots.id = release_bundles.materialization_id
JOIN attribute_snapshots
    ON attribute_snapshots.id = materialization_snapshots.attribute_snapshot_id
   AND attribute_snapshots.catalog_generation_id =
       materialization_snapshots.catalog_generation_id
JOIN index_versions
    ON index_versions.id = release_bundles.index_version_id
   AND index_versions.materialization_id = materialization_snapshots.id
JOIN relation_snapshots
    ON relation_snapshots.id = release_bundles.relation_snapshot_id
WHERE release_bundles.status = 'ready'
  AND materialization_snapshots.status = 'complete'
  AND attribute_snapshots.status = 'complete'
  AND index_versions.status = 'complete'
  AND relation_snapshots.status = 'complete'
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

DROP TRIGGER guard_active_release_insert;

CREATE TRIGGER guard_active_release_insert
BEFORE INSERT ON active_release
WHEN NOT EXISTS (
    SELECT 1
    FROM release_bundles
    JOIN materialization_snapshots
      ON materialization_snapshots.id = release_bundles.materialization_id
    JOIN attribute_snapshots
      ON attribute_snapshots.id = materialization_snapshots.attribute_snapshot_id
     AND attribute_snapshots.catalog_generation_id =
         materialization_snapshots.catalog_generation_id
    JOIN index_versions
      ON index_versions.id = release_bundles.index_version_id
     AND index_versions.materialization_id = materialization_snapshots.id
    JOIN relation_snapshots
      ON relation_snapshots.id = release_bundles.relation_snapshot_id
    WHERE release_bundles.id = NEW.bundle_id
      AND release_bundles.status = 'ready'
      AND materialization_snapshots.status = 'complete'
      AND attribute_snapshots.status = 'complete'
      AND index_versions.status = 'complete'
      AND relation_snapshots.status = 'complete'
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

DROP TRIGGER guard_active_release_update;

CREATE TRIGGER guard_active_release_update
BEFORE UPDATE OF bundle_id ON active_release
WHEN NOT EXISTS (
    SELECT 1
    FROM release_bundles
    JOIN materialization_snapshots
      ON materialization_snapshots.id = release_bundles.materialization_id
    JOIN attribute_snapshots
      ON attribute_snapshots.id = materialization_snapshots.attribute_snapshot_id
     AND attribute_snapshots.catalog_generation_id =
         materialization_snapshots.catalog_generation_id
    JOIN index_versions
      ON index_versions.id = release_bundles.index_version_id
     AND index_versions.materialization_id = materialization_snapshots.id
    JOIN relation_snapshots
      ON relation_snapshots.id = release_bundles.relation_snapshot_id
    WHERE release_bundles.id = NEW.bundle_id
      AND release_bundles.status = 'ready'
      AND materialization_snapshots.status = 'complete'
      AND attribute_snapshots.status = 'complete'
      AND index_versions.status = 'complete'
      AND relation_snapshots.status = 'complete'
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

CREATE TRIGGER guard_active_materialization_update
BEFORE UPDATE ON materialization_snapshots
WHEN EXISTS (
    SELECT 1 FROM active_release
    JOIN release_bundles ON release_bundles.id = active_release.bundle_id
    WHERE release_bundles.materialization_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'active release dependency is immutable');
END;

CREATE TRIGGER guard_active_attribute_update
BEFORE UPDATE ON attribute_snapshots
WHEN EXISTS (
    SELECT 1 FROM active_release
    JOIN release_bundles ON release_bundles.id = active_release.bundle_id
    JOIN materialization_snapshots
      ON materialization_snapshots.id = release_bundles.materialization_id
    WHERE materialization_snapshots.attribute_snapshot_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'active release dependency is immutable');
END;

CREATE TRIGGER guard_active_index_update
BEFORE UPDATE ON index_versions
WHEN EXISTS (
    SELECT 1 FROM active_release
    JOIN release_bundles ON release_bundles.id = active_release.bundle_id
    WHERE release_bundles.index_version_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'active release dependency is immutable');
END;

CREATE TRIGGER guard_active_relation_update
BEFORE UPDATE ON relation_snapshots
WHEN EXISTS (
    SELECT 1 FROM active_release
    JOIN release_bundles ON release_bundles.id = active_release.bundle_id
    WHERE release_bundles.relation_snapshot_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'active release dependency is immutable');
END;

CREATE TRIGGER guard_active_bundle_update
BEFORE UPDATE ON release_bundles
WHEN EXISTS (
    SELECT 1 FROM active_release WHERE active_release.bundle_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'active release bundle is immutable');
END;

CREATE TRIGGER guard_active_cache_insert
BEFORE INSERT ON comparator_cache
WHEN EXISTS (
    SELECT 1 FROM active_release
    WHERE active_release.bundle_id = NEW.release_bundle_id
)
BEGIN
    SELECT RAISE(ABORT, 'active release cache is immutable');
END;

CREATE TRIGGER guard_active_cache_update
BEFORE UPDATE ON comparator_cache
WHEN EXISTS (
    SELECT 1 FROM active_release
    WHERE active_release.bundle_id IN (
        OLD.release_bundle_id, NEW.release_bundle_id
    )
)
BEGIN
    SELECT RAISE(ABORT, 'active release cache is immutable');
END;

CREATE TRIGGER guard_active_cache_delete
BEFORE DELETE ON comparator_cache
WHEN EXISTS (
    SELECT 1 FROM active_release
    WHERE active_release.bundle_id = OLD.release_bundle_id
)
BEGIN
    SELECT RAISE(ABORT, 'active release cache is immutable');
END;
