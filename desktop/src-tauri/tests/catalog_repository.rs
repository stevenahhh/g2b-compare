use std::{error::Error, path::Path};

use g2b_compare_desktop_lib::{
    catalog::{CatalogError, CatalogRepository, CatalogSort, RelationCategory},
    db::{CatalogCacheError, CatalogCacheStore, advance_catalog_cache_version},
};
use rusqlite::Connection;
use tempfile::tempdir;

#[test]
fn searches_name_spec_and_company_with_all_sorts() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("catalog.sqlite3");
    create_catalog_fixture(&database, 34)?;
    let repository = CatalogRepository::open(&database)?;

    let by_name = repository.products("", "의자", CatalogSort::PriceAsc, 1)?;
    assert_eq!(by_name.total_count, 34);
    assert_eq!(
        by_name.items.first().map(|item| item.price_won),
        Some(1_000)
    );

    let by_spec = repository.products("", "규격-07", CatalogSort::PriceDesc, 1)?;
    assert_eq!(by_spec.total_count, 1);
    assert_eq!(by_spec.items[0].product_id, "P0000007");

    let by_company = repository.products("", "주식회사 한빛", CatalogSort::NameAsc, 1)?;
    assert_eq!(by_company.total_count, 34);
    assert_eq!(by_company.items[0].name, "의자 01");

    let by_product_id = repository.products("", "", CatalogSort::ProductIdAsc, 1)?;
    assert_eq!(by_product_id.items[0].product_id, "P0000001");

    let preferred_company =
        repository.products("주식회사 한빛", "", CatalogSort::ProductIdAsc, 1)?;
    assert_eq!(preferred_company.total_count, 34);
    let other_company =
        repository.products("주식회사 코리아넷", "", CatalogSort::ProductIdAsc, 1)?;
    assert_eq!(other_company.total_count, 0);
    Ok(())
}

#[test]
fn paginates_by_thirty_and_rejects_invalid_page() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("catalog.sqlite3");
    create_catalog_fixture(&database, 34)?;
    let repository = CatalogRepository::open(&database)?;

    let first = repository.products("", "", CatalogSort::ProductIdAsc, 1)?;
    assert_eq!(first.items.len(), 30);
    assert_eq!(first.page, 1);
    assert_eq!(first.page_count, 2);
    assert_eq!(first.total_count, 34);

    let second = repository.products("", "", CatalogSort::ProductIdAsc, 2)?;
    assert_eq!(second.items.len(), 4);
    assert_eq!(second.items[0].product_id, "P0000031");

    assert!(matches!(
        repository.products("", "", CatalogSort::PriceAsc, 0),
        Err(CatalogError::InvalidPage)
    ));
    Ok(())
}

#[test]
fn offline_catalog_search_uses_the_persisted_validated_cache_version() -> Result<(), Box<dyn Error>>
{
    let temporary = tempdir()?;
    let database = temporary.path().join("g2b.sqlite3");
    create_catalog_fixture(&database, 1)?;
    let initial = CatalogCacheStore::initialize(&database)?;
    let reader = CatalogRepository::open_with_cache(&database, initial)?;

    assert_eq!(
        reader
            .products("", "의자", CatalogSort::ProductIdAsc, 1)?
            .total_count,
        1
    );

    let connection = Connection::open(&database)?;
    connection.execute_batch("BEGIN IMMEDIATE")?;
    let advanced = advance_catalog_cache_version(&connection)?;
    connection.execute_batch("COMMIT")?;
    assert!(matches!(
        reader.products("", "의자", CatalogSort::ProductIdAsc, 1),
        Err(CatalogError::Cache(CatalogCacheError::VersionMismatch))
    ));

    let restarted = CatalogCacheStore::open(&database)?;
    assert_eq!(restarted.version()?, advanced);
    assert_eq!(
        CatalogRepository::open_with_cache(&database, restarted.version()?)?
            .products("", "의자", CatalogSort::ProductIdAsc, 1)?
            .total_count,
        1
    );
    Ok(())
}

#[test]
fn groups_options_and_filters_three_relation_categories() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("catalog.sqlite3");
    create_catalog_fixture(&database, 1)?;
    let repository = CatalogRepository::open(&database)?;

    let grouped = repository.options("P0000001")?;
    assert_eq!(grouped.len(), 3);
    assert_eq!(grouped[0].parent_product_id, "P0000001");

    let selection = repository.relations(
        "P0000001",
        "주식회사 한빛",
        RelationCategory::Selection,
        "",
        CatalogSort::PriceAsc,
        1,
    )?;
    assert_eq!(
        selection
            .items
            .iter()
            .map(|item| item.product_id.as_str())
            .collect::<Vec<_>>(),
        ["O0000001"]
    );

    let additional = repository.relations(
        "P0000001",
        "주식회사 한빛",
        RelationCategory::Additional,
        "추가",
        CatalogSort::PriceAsc,
        1,
    )?;
    assert_eq!(additional.items[0].product_id, "O0000002");

    let construction = repository.relations(
        "P0000001",
        "주식회사 한빛",
        RelationCategory::Construction,
        "",
        CatalogSort::PriceAsc,
        1,
    )?;
    assert_eq!(construction.items[0].product_id, "O0000003");
    Ok(())
}

fn create_catalog_fixture(path: &Path, product_count: usize) -> Result<(), rusqlite::Error> {
    let connection = Connection::open(path)?;
    create_product_schema(&connection)?;
    create_relation_schema(&connection)?;
    insert_products(&connection, product_count)?;
    insert_options(&connection)
}

fn create_product_schema(connection: &Connection) -> Result<(), rusqlite::Error> {
    connection.execute_batch(
        "
        CREATE TABLE priority_products (
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
        CREATE TABLE priority_product_offers (
            operation TEXT NOT NULL,
            offer_key TEXT NOT NULL,
            product_id TEXT NOT NULL,
            company_name TEXT NOT NULL DEFAULT '',
            price_won INTEGER NOT NULL DEFAULT 0,
            unit TEXT NOT NULL DEFAULT '',
            contract_method TEXT NOT NULL DEFAULT '',
            delivery_condition TEXT NOT NULL DEFAULT '',
            delivery_days TEXT NOT NULL DEFAULT '',
            contract_end_date TEXT NOT NULL DEFAULT '',
            image_url TEXT NOT NULL DEFAULT '',
            detail_url TEXT NOT NULL DEFAULT '',
            raw_json TEXT NOT NULL DEFAULT '{}',
            observed_at TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (operation, offer_key)
        );
        ",
    )
}

fn create_relation_schema(connection: &Connection) -> Result<(), rusqlite::Error> {
    connection.execute_batch(
        "
        CREATE TABLE priority_options (
            source_row INTEGER PRIMARY KEY,
            company_name TEXT NOT NULL,
            option_kind TEXT NOT NULL,
            product_id TEXT NOT NULL,
            item_name TEXT NOT NULL,
            spec TEXT NOT NULL,
            price_won INTEGER NOT NULL,
            details TEXT NOT NULL
        );
        CREATE TABLE priority_product_contract_groups (
            product_id TEXT PRIMARY KEY,
            contract_group TEXT NOT NULL
        );
        CREATE TABLE priority_contract_options (
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
        CREATE TABLE verified_product_options (
            relation_id TEXT PRIMARY KEY,
            parent_operation TEXT NOT NULL,
            parent_offer_key TEXT NOT NULL,
            parent_product_id TEXT NOT NULL,
            option_product_id TEXT NOT NULL,
            relation_kind TEXT NOT NULL,
            position INTEGER NOT NULL,
            company_name TEXT NOT NULL,
            raw_label TEXT NOT NULL,
            relation_price_won INTEGER NOT NULL DEFAULT 0,
            detail_url TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
        ",
    )
}

fn insert_products(connection: &Connection, product_count: usize) -> Result<(), rusqlite::Error> {
    for index in 1..=product_count {
        let product_id = format!("P{index:07}");
        let price_won = i64::try_from(index).unwrap_or(0) * 1_000;
        connection.execute(
            "INSERT INTO priority_products VALUES (
                ?1, 'getThngListInfo', 'C-1', '1', '1', ?2, '1', ?3,
                '주식회사 한빛', '개', ?4, 'MAS', '현장도착도', '10',
                '2027-12-31', '', ?5, '{}', '2026-08-04', '', ''
            )",
            (
                &product_id,
                format!("의자 {index:02}"),
                format!("규격-{index:02}"),
                price_won,
                format!("https://example.test/products/{index}"),
            ),
        )?;
        connection.execute(
            "INSERT INTO priority_product_offers (
                operation, offer_key, product_id, company_name, price_won, active
            ) VALUES ('getThngListInfo', ?1, ?2, '주식회사 한빛', ?3, 1)",
            (format!("offer-{index}"), product_id, price_won),
        )?;
    }
    Ok(())
}

fn insert_options(connection: &Connection) -> Result<(), rusqlite::Error> {
    connection.execute(
        "INSERT INTO priority_product_contract_groups VALUES ('P0000001', 'group-1')",
        [],
    )?;
    for (position, (relation_id, product_id, relation_kind, name, price)) in [
        ("R0000001", "O0000001", "component", "선택 품목", 5_000_i64),
        ("R0000002", "O0000002", "additional", "추가 품목", 3_000),
        ("R0000003", "O0000003", "additional", "정보통신공사", 7_000),
    ]
    .into_iter()
    .enumerate()
    {
        connection.execute(
            "INSERT INTO priority_options VALUES (
                ?1, '주식회사 한빛', ?2, ?3, ?4, '', ?5, ''
            )",
            (
                i64::try_from(position).unwrap_or(0) + 1,
                relation_kind,
                product_id,
                name,
                price,
            ),
        )?;
        connection.execute(
            "INSERT INTO priority_contract_options VALUES (
                'group-1', ?1, ?2, ?3, ?4, '주식회사 한빛', '', ?5,
                '2026-08-04', 1
            )",
            (
                relation_id,
                product_id,
                relation_kind,
                i64::try_from(position).unwrap_or(0),
                price,
            ),
        )?;
    }
    Ok(())
}
