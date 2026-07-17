"""Frozen E0 release reader integration contract."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing

from g2b_compare.evaluation.e0_reader import read_frozen_e0_release
from g2b_compare.services.release_models import ReleasePin


def test_reader_projects_only_the_pinned_materialization() -> None:
    # Given: one minimal pinned release graph with search, price, and source rows
    with closing(sqlite3.connect(":memory:")) as connection:
        _ = connection.executescript(
            """CREATE TABLE release_bundles(
                id INTEGER, release_bundle_sha TEXT, created_at TEXT
            );
            CREATE TABLE search_index_members(
                materialization_id INTEGER, member_name TEXT, member_bytes BLOB
            );
            CREATE TABLE products(
                materialization_id INTEGER, product_id TEXT, category_no TEXT,
                detail_category_no TEXT, product_name_key TEXT, active INTEGER
            );
            CREATE TABLE search_membership(
                materialization_id INTEGER, product_id TEXT,
                option_text TEXT, active INTEGER
            );
            CREATE TABLE product_attributes(
                materialization_id INTEGER, product_id TEXT, attribute_key TEXT,
                attribute_source_key TEXT, ordinal INTEGER, raw_value TEXT
            );
            CREATE TABLE catalog_offers(
                materialization_id INTEGER, product_id TEXT, operation TEXT,
                offer_key TEXT, contract_price_won INTEGER,
                unit_key TEXT, active INTEGER
            );"""
        )
        _ = connection.execute(
            "INSERT INTO release_bundles VALUES(7,?,?)",
            ("a" * 64, "2026-07-14T00:00:00Z"),
        )
        _ = connection.executemany(
            "INSERT INTO search_index_members VALUES(11,?,?)",
            (("char-idf.f64le", b"char"), ("word-idf.f64le", b"word")),
        )
        _ = connection.execute(
            "INSERT INTO products VALUES(11,'P-1','C','D','영상감시장치',1)"
        )
        _ = connection.execute(
            "INSERT INTO products VALUES(11,'P-2','C','D','영상감시장치',0)"
        )
        _ = connection.execute(
            "INSERT INTO search_membership VALUES(11,'P-1','spec:8MP | detail:방수',1)"
        )
        _ = connection.execute(
            "INSERT INTO search_membership VALUES(11,'P-2','spec:INACTIVE-99',0)"
        )
        _ = connection.execute(
            "INSERT INTO product_attributes VALUES(11,'P-1','resolution','A-1',0,'8MP')"
        )
        _ = connection.execute(
            "INSERT INTO product_attributes VALUES(?,?,?,?,?,?)",
            (11, "P-2", "inactive", "A-2", 0, "INACTIVE-99"),
        )
        _ = connection.execute(
            "INSERT INTO catalog_offers VALUES(11,'P-1','mas','O-1',100000,'대',1)"
        )
        pin = ReleasePin(
            7,
            1,
            11,
            12,
            13,
            "v1",
            "normalization-v1",
            "policy-v1",
            "b" * 64,
            "c" * 64,
            "d" * 64,
            "e" * 64,
            "f" * 64,
            "2026-07-14T00:00:00Z",
        )

        # When: the query-only snapshot is projected
        release = read_frozen_e0_release(connection, pin)

    # Then: component hashes and canonical source fields remain pinned
    assert release.identity.release_bundle_sha == "a" * 64
    assert release.identity.char_idf_sha == hashlib.sha256(b"char").hexdigest()
    assert release.products[0].price_won == 100_000
    assert {source.field_kind for source in release.parser_sources} == {
        "raw_value",
        "spec_name",
        "detail",
    }
    assert {source.product_id for source in release.parser_sources} == {"P-1"}
