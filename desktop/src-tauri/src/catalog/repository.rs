use std::{cmp::Ordering, path::Path};

use rusqlite::{Connection, OpenFlags, named_params};
use thiserror::Error;

use crate::db::{CatalogCacheError, CatalogCacheVersion, validate_catalog_cache_version};

use super::{
    CATALOG_PAGE_SIZE, CatalogOption, CatalogPage, CatalogProduct, CatalogSort, RelationCategory,
    RelationKind,
};

const ACTIVE_PRODUCTS: &str = "
FROM priority_products AS product
WHERE EXISTS (
    SELECT 1
    FROM priority_product_offers AS offer
    WHERE offer.product_id = product.product_id AND offer.active = 1
)
AND NOT EXISTS (
    SELECT 1
    FROM verified_product_options AS child_relation
    WHERE child_relation.option_product_id = product.product_id
      AND child_relation.active = 1
)
AND NOT EXISTS (
    SELECT 1
    FROM priority_contract_options AS contract_child
    WHERE contract_child.option_product_id = product.product_id
      AND contract_child.active = 1
)
AND (:company_name = '' OR product.company_name = :company_name)
AND (
    :query = ''
    OR instr(lower(product.category_name), lower(:query)) > 0
    OR instr(lower(product.spec), lower(:query)) > 0
    OR instr(lower(product.company_name), lower(:query)) > 0
    OR instr(lower(product.product_id), lower(:query)) > 0
)
";

const OPTIONS: &str = "
WITH option_first AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY company_name, product_id ORDER BY source_row
    ) AS occurrence
    FROM priority_options
), product_group_first AS (
    SELECT contract_group, MIN(product_id) AS product_id
    FROM priority_product_contract_groups
    WHERE (:parent_product_id = '' OR product_id = :parent_product_id)
    GROUP BY contract_group
), contract_rows AS (
    SELECT product_group.product_id AS parent_product_id,
           parent.category_name AS parent_name,
           COALESCE(option.item_name, '추가선택품목') AS item_name,
           COALESCE(NULLIF(relation.raw_label, ''), option.spec) AS spec,
           COALESCE(NULLIF(product.unit, ''), '개') AS unit,
           relation.relation_price_won AS relation_price_won,
           relation.option_product_id AS option_product_id,
           relation.company_name AS company_name,
           parent.detail_url AS detail_url,
           relation.relation_id AS relation_id,
           relation.relation_kind AS relation_kind,
           COALESCE(product.image_url, '') AS image_url,
           relation.position AS position
    FROM product_group_first AS product_group
    JOIN priority_contract_options AS relation
      ON relation.contract_group = product_group.contract_group
    LEFT JOIN option_first AS option
      ON option.company_name = relation.company_name
     AND option.product_id = relation.option_product_id
     AND option.occurrence = 1
    LEFT JOIN priority_products AS product
      ON product.product_id = relation.option_product_id
    JOIN priority_products AS parent
      ON parent.product_id = product_group.product_id
    WHERE (:company_name = '' OR relation.company_name = :company_name)
      AND relation.active = 1
), legacy_rows AS (
    SELECT relation.parent_product_id AS parent_product_id,
           parent.category_name AS parent_name,
           COALESCE(option.item_name, '추가선택품목') AS item_name,
           COALESCE(NULLIF(relation.raw_label, ''), option.spec) AS spec,
           COALESCE(NULLIF(product.unit, ''), '개') AS unit,
           relation.relation_price_won AS relation_price_won,
           relation.option_product_id AS option_product_id,
           relation.company_name AS company_name,
           relation.detail_url AS detail_url,
           relation.relation_id AS relation_id,
           relation.relation_kind AS relation_kind,
           COALESCE(product.image_url, '') AS image_url,
           relation.position AS position
    FROM verified_product_options AS relation
    JOIN priority_products AS parent
      ON parent.product_id = relation.parent_product_id
    LEFT JOIN option_first AS option
      ON option.company_name = relation.company_name
     AND option.product_id = relation.option_product_id
     AND option.occurrence = 1
    LEFT JOIN priority_products AS product
      ON product.product_id = relation.option_product_id
    WHERE (:parent_product_id = '' OR relation.parent_product_id = :parent_product_id)
      AND (:company_name = '' OR relation.company_name = :company_name)
      AND relation.active = 1
)
SELECT parent_product_id, parent_name, item_name, spec, unit,
       relation_price_won, option_product_id, company_name, detail_url,
       relation_id, relation_kind, image_url, position
FROM contract_rows
UNION ALL
SELECT parent_product_id, parent_name, item_name, spec, unit,
       relation_price_won, option_product_id, company_name, detail_url,
       relation_id, relation_kind, image_url, position
FROM legacy_rows
WHERE NOT EXISTS (
    SELECT 1
    FROM contract_rows
    WHERE contract_rows.parent_product_id = legacy_rows.parent_product_id
)
ORDER BY position, option_product_id, relation_id
";

#[derive(Debug, Error)]
pub enum CatalogError {
    #[error("catalog page must be at least one")]
    InvalidPage,
    #[error("catalog database contains unsupported relation kind: {0}")]
    UnsupportedRelationKind(String),
    #[error("catalog result is outside the supported numeric range")]
    NumericRange,
    #[error(transparent)]
    Cache(#[from] CatalogCacheError),
    #[error("catalog database operation failed: {0}")]
    Sqlite(#[from] rusqlite::Error),
}

#[derive(Clone, Debug)]
pub struct CatalogRepository {
    database: std::path::PathBuf,
    cache_version: Option<CatalogCacheVersion>,
}

impl CatalogRepository {
    /// Opens and validates a read-only production catalog database.
    ///
    /// # Errors
    ///
    /// Returns an error when the database cannot be opened or does not contain
    /// the production catalog schema.
    pub fn open(database: impl AsRef<Path>) -> Result<Self, CatalogError> {
        Self::open_inner(database, None)
    }

    /// Opens a catalog reader pinned to one validated durable catalog version.
    ///
    /// Every query verifies this pin inside its own read snapshot, so a concurrent successful
    /// publication cannot mix catalog rows from one version with another.
    ///
    /// # Errors
    ///
    /// Returns an error when the catalog schema or supplied canonical cache pin is invalid.
    pub fn open_with_cache(
        database: impl AsRef<Path>,
        cache_version: CatalogCacheVersion,
    ) -> Result<Self, CatalogError> {
        Self::open_inner(database, Some(cache_version))
    }

    fn open_inner(
        database: impl AsRef<Path>,
        cache_version: Option<CatalogCacheVersion>,
    ) -> Result<Self, CatalogError> {
        let database = database.as_ref().to_path_buf();
        let connection = open_read_only(&database)?;
        {
            let _statement = connection.prepare(
                "SELECT product_id, category_name, spec, company_name, price_won
                 FROM priority_products LIMIT 0",
            )?;
        }
        Ok(Self {
            database,
            cache_version,
        })
    }

    fn connection(&self) -> Result<Connection, CatalogError> {
        let connection = open_read_only(&self.database)?;
        if let Some(cache_version) = &self.cache_version {
            connection.execute_batch("BEGIN")?;
            validate_catalog_cache_version(&connection, cache_version)?;
        }
        Ok(connection)
    }

    /// Searches active main products and returns one fixed 30-row page.
    ///
    /// # Errors
    ///
    /// Returns an error for page zero, an invalid schema, or a failed database
    /// query.
    pub fn products(
        &self,
        company_name: &str,
        query: &str,
        sort: CatalogSort,
        page: u32,
    ) -> Result<CatalogPage<CatalogProduct>, CatalogError> {
        let offset = page_offset(page)?;
        let connection = self.connection()?;
        let company_name = company_name.trim();
        let query = query.trim();
        let count_sql = format!("SELECT COUNT(*) {ACTIVE_PRODUCTS}");
        let total_count = count(&connection, &count_sql, company_name, query)?;
        let select_sql = format!(
            "SELECT product.product_id, product.category_name, product.spec,
                    product.company_name, product.unit, product.price_won,
                    product.contract_method, product.delivery_condition,
                    product.delivery_days, product.contract_end_date,
                    product.image_url, product.detail_url
             {ACTIVE_PRODUCTS}
             ORDER BY {}
             LIMIT :limit OFFSET :offset",
            product_order(sort)
        );
        let mut statement = connection.prepare(&select_sql)?;
        let limit = i64::try_from(CATALOG_PAGE_SIZE).map_err(|_| CatalogError::NumericRange)?;
        let rows = statement.query_map(
            named_params! {
                ":company_name": company_name,
                ":query": query,
                ":limit": limit,
                ":offset": offset,
            },
            |row| {
                let detail_url = row.get::<_, String>(11)?;
                Ok(CatalogProduct {
                    product_id: row.get(0)?,
                    name: row.get(1)?,
                    spec: row.get(2)?,
                    company_name: row.get(3)?,
                    unit: row.get(4)?,
                    price_won: row.get(5)?,
                    contract_method: row.get(6)?,
                    delivery_condition: row.get(7)?,
                    delivery_days: row.get(8)?,
                    contract_end_date: row.get(9)?,
                    image_url: row.get(10)?,
                    g2b_url: detail_url.clone(),
                    detail_url,
                })
            },
        )?;
        let items = rows.collect::<Result<Vec<_>, _>>()?;
        Ok(CatalogPage {
            items,
            page,
            page_count: page_count(total_count),
            total_count,
        })
    }

    /// Returns every active option grouped under the requested parent product.
    ///
    /// # Errors
    ///
    /// Returns an error when the production option schema is invalid or a
    /// relation kind is unsupported.
    pub fn options(&self, parent_product_id: &str) -> Result<Vec<CatalogOption>, CatalogError> {
        self.load_options(parent_product_id, "")
    }

    /// Searches one parent product's relation category and returns a 30-row page.
    ///
    /// # Errors
    ///
    /// Returns an error for page zero, an invalid schema, an unsupported
    /// relation kind, or a failed database query.
    pub fn relations(
        &self,
        parent_product_id: &str,
        company_name: &str,
        category: RelationCategory,
        query: &str,
        sort: CatalogSort,
        page: u32,
    ) -> Result<CatalogPage<CatalogOption>, CatalogError> {
        let offset = usize::try_from(page_offset(page)?).map_err(|_| CatalogError::NumericRange)?;
        let terms = query
            .split_whitespace()
            .map(str::to_lowercase)
            .collect::<Vec<_>>();
        let mut items = self.load_options(parent_product_id, company_name)?;
        items.retain(|item| {
            item.category == category
                && (terms.is_empty()
                    || terms
                        .iter()
                        .all(|term| option_document(item).contains(term)))
        });
        items.sort_by(|left, right| compare_options(left, right, sort));
        let total_count = u64::try_from(items.len()).map_err(|_| CatalogError::NumericRange)?;
        let items = items
            .into_iter()
            .skip(offset)
            .take(usize::try_from(CATALOG_PAGE_SIZE).map_err(|_| CatalogError::NumericRange)?)
            .collect();
        Ok(CatalogPage {
            items,
            page,
            page_count: page_count(total_count),
            total_count,
        })
    }

    fn load_options(
        &self,
        parent_product_id: &str,
        company_name: &str,
    ) -> Result<Vec<CatalogOption>, CatalogError> {
        let connection = self.connection()?;
        let mut statement = connection.prepare(OPTIONS)?;
        let rows = statement.query_map(
            named_params! {
                ":parent_product_id": parent_product_id,
                ":company_name": company_name,
            },
            |row| {
                Ok(RawOption {
                    parent_product_id: row.get(0)?,
                    parent_name: row.get(1)?,
                    item_name: row.get(2)?,
                    spec: row.get(3)?,
                    unit: row.get(4)?,
                    price_won: row.get(5)?,
                    product_id: row.get(6)?,
                    company_name: row.get(7)?,
                    detail_url: row.get(8)?,
                    relation_id: row.get(9)?,
                    relation_kind: row.get(10)?,
                    image_url: row.get(11)?,
                })
            },
        )?;
        rows.map(|row| {
            row.map_err(CatalogError::from)
                .and_then(CatalogOption::try_from)
        })
        .collect()
    }
}

#[derive(Debug)]
struct RawOption {
    parent_product_id: String,
    parent_name: String,
    item_name: String,
    spec: String,
    unit: String,
    price_won: i64,
    product_id: String,
    company_name: String,
    detail_url: String,
    relation_id: String,
    relation_kind: String,
    image_url: String,
}

impl TryFrom<RawOption> for CatalogOption {
    type Error = CatalogError;

    fn try_from(raw: RawOption) -> Result<Self, Self::Error> {
        let relation_kind = match raw.relation_kind.as_str() {
            "additional" => RelationKind::Additional,
            "component" => RelationKind::Component,
            unsupported => {
                return Err(CatalogError::UnsupportedRelationKind(
                    unsupported.to_owned(),
                ));
            }
        };
        let (name, spec) = option_name_spec(raw.item_name, raw.spec);
        let category = if name.contains("공사") || spec.contains("공사") {
            RelationCategory::Construction
        } else if relation_kind == RelationKind::Component {
            RelationCategory::Selection
        } else {
            RelationCategory::Additional
        };
        Ok(Self {
            parent_product_id: raw.parent_product_id,
            parent_name: raw.parent_name,
            relation_id: raw.relation_id,
            relation_kind,
            category,
            product_id: raw.product_id,
            name,
            spec,
            unit: raw.unit,
            price_won: raw.price_won,
            company_name: raw.company_name,
            g2b_url: raw.detail_url.clone(),
            detail_url: raw.detail_url,
            image_url: raw.image_url,
        })
    }
}

fn open_read_only(path: &Path) -> Result<Connection, rusqlite::Error> {
    let connection = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    connection.pragma_update(None, "query_only", true)?;
    Ok(connection)
}

fn count(
    connection: &Connection,
    sql: &str,
    company_name: &str,
    query: &str,
) -> Result<u64, CatalogError> {
    let value = connection.query_row(
        sql,
        named_params! { ":company_name": company_name, ":query": query },
        |row| row.get::<_, i64>(0),
    )?;
    u64::try_from(value).map_err(|_| CatalogError::NumericRange)
}

fn page_offset(page: u32) -> Result<i64, CatalogError> {
    if page == 0 {
        return Err(CatalogError::InvalidPage);
    }
    i64::from(page - 1)
        .checked_mul(i64::try_from(CATALOG_PAGE_SIZE).map_err(|_| CatalogError::NumericRange)?)
        .ok_or(CatalogError::NumericRange)
}

fn page_count(total_count: u64) -> u64 {
    total_count.div_ceil(CATALOG_PAGE_SIZE).max(1)
}

const fn product_order(sort: CatalogSort) -> &'static str {
    match sort {
        CatalogSort::PriceAsc => {
            "product.price_won ASC, product.category_name COLLATE NOCASE ASC, product.product_id ASC"
        }
        CatalogSort::PriceDesc => {
            "product.price_won DESC, product.category_name COLLATE NOCASE ASC, product.product_id ASC"
        }
        CatalogSort::NameAsc => "product.category_name COLLATE NOCASE ASC, product.product_id ASC",
        CatalogSort::ProductIdAsc => {
            "product.product_id COLLATE NOCASE ASC, product.category_name COLLATE NOCASE ASC"
        }
    }
}

fn option_document(item: &CatalogOption) -> String {
    format!(
        "{} {} {} {} {} {}",
        item.name,
        item.spec,
        item.product_id,
        item.company_name,
        item.parent_name,
        item.parent_product_id
    )
    .to_lowercase()
}

fn compare_options(left: &CatalogOption, right: &CatalogOption, sort: CatalogSort) -> Ordering {
    let left_name = left.name.to_lowercase();
    let right_name = right.name.to_lowercase();
    match sort {
        CatalogSort::PriceAsc => left
            .price_won
            .cmp(&right.price_won)
            .then_with(|| left_name.cmp(&right_name))
            .then_with(|| left.product_id.cmp(&right.product_id))
            .then_with(|| left.relation_id.cmp(&right.relation_id)),
        CatalogSort::PriceDesc => right
            .price_won
            .cmp(&left.price_won)
            .then_with(|| left_name.cmp(&right_name))
            .then_with(|| left.product_id.cmp(&right.product_id))
            .then_with(|| left.relation_id.cmp(&right.relation_id)),
        CatalogSort::NameAsc => left_name
            .cmp(&right_name)
            .then_with(|| left.product_id.cmp(&right.product_id))
            .then_with(|| left.relation_id.cmp(&right.relation_id)),
        CatalogSort::ProductIdAsc => left
            .product_id
            .cmp(&right.product_id)
            .then_with(|| left_name.cmp(&right_name))
            .then_with(|| left.relation_id.cmp(&right.relation_id)),
    }
}

fn option_name_spec(item_name: String, spec: String) -> (String, String) {
    if let Some((parsed_name, parsed_spec)) = parse_relation_label(&spec) {
        return (parsed_name.to_owned(), parsed_spec.to_owned());
    }
    (item_name, spec)
}

fn parse_relation_label(value: &str) -> Option<(&str, &str)> {
    let (_, after_kind) = value.strip_prefix('[')?.split_once(']')?;
    let after_kind = after_kind.trim_start().strip_prefix('[')?;
    let (product_id, body) = after_kind.split_once(']')?;
    if product_id.chars().count() != 8 || !product_id.chars().all(|value| value.is_ascii_digit()) {
        return None;
    }
    let (name, spec_and_price) = body.trim_start().split_once(',')?;
    let (spec, price) = spec_and_price.rsplit_once(':')?;
    let price = price.trim();
    if price.is_empty()
        || !price
            .chars()
            .all(|value| value.is_ascii_digit() || value == ',')
    {
        return None;
    }
    Some((name.trim(), spec.trim()))
}
