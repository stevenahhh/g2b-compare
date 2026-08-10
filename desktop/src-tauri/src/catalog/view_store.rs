use std::{fs, io, path::PathBuf, time::Duration};

use rusqlite::{Connection, OptionalExtension, params};
use thiserror::Error;

use crate::db::{Migration, MigrationError, apply_migrations};

use super::{CatalogSort, CatalogViewState, RelationCategory, RelationValues};

const VIEW_MIGRATIONS: [Migration; 1] = [Migration::new(
    "0001_initial",
    "
CREATE TABLE IF NOT EXISTS catalog_view_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    query TEXT NOT NULL,
    sort TEXT NOT NULL,
    page INTEGER NOT NULL,
    selected_product_id TEXT,
    active_category TEXT NOT NULL,
    product_scroll_top REAL NOT NULL,
    selection_scroll_top REAL NOT NULL,
    additional_scroll_top REAL NOT NULL,
    construction_scroll_top REAL NOT NULL,
    selection_query TEXT NOT NULL,
    additional_query TEXT NOT NULL,
    construction_query TEXT NOT NULL,
    selection_page INTEGER NOT NULL,
    additional_page INTEGER NOT NULL,
    construction_page INTEGER NOT NULL
);
",
)];

const SELECT_VIEW: &str = "
SELECT query, sort, page, selected_product_id, active_category,
       product_scroll_top, selection_scroll_top, additional_scroll_top,
       construction_scroll_top, selection_query, additional_query,
       construction_query, selection_page, additional_page, construction_page
FROM catalog_view_state
WHERE singleton = 1
";

const UPSERT_VIEW: &str = "
INSERT INTO catalog_view_state (
    singleton, query, sort, page, selected_product_id, active_category,
    product_scroll_top, selection_scroll_top, additional_scroll_top,
    construction_scroll_top, selection_query, additional_query,
    construction_query, selection_page, additional_page, construction_page
) VALUES (
    1, ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15
)
ON CONFLICT(singleton) DO UPDATE SET
    query = excluded.query,
    sort = excluded.sort,
    page = excluded.page,
    selected_product_id = excluded.selected_product_id,
    active_category = excluded.active_category,
    product_scroll_top = excluded.product_scroll_top,
    selection_scroll_top = excluded.selection_scroll_top,
    additional_scroll_top = excluded.additional_scroll_top,
    construction_scroll_top = excluded.construction_scroll_top,
    selection_query = excluded.selection_query,
    additional_query = excluded.additional_query,
    construction_query = excluded.construction_query,
    selection_page = excluded.selection_page,
    additional_page = excluded.additional_page,
    construction_page = excluded.construction_page
";

#[derive(Debug, Error)]
pub enum CatalogViewStoreError {
    #[error("catalog view path has no parent directory")]
    MissingParent,
    #[error("catalog view contains unsupported sort: {0}")]
    UnsupportedSort(String),
    #[error("catalog view contains unsupported relation category: {0}")]
    UnsupportedCategory(String),
    #[error("catalog view contains a page outside the supported numeric range")]
    NumericRange,
    #[error("catalog view state is invalid: {0}")]
    InvalidState(&'static str),
    #[error("catalog view I/O failed: {0}")]
    Io(#[from] io::Error),
    #[error(transparent)]
    Migration(#[from] MigrationError),
    #[error("catalog view database operation failed: {0}")]
    Sqlite(#[from] rusqlite::Error),
}

#[derive(Clone, Debug)]
pub struct CatalogViewStore {
    path: PathBuf,
}

impl CatalogViewStore {
    pub fn open(path: PathBuf) -> Result<Self, CatalogViewStoreError> {
        let parent = path.parent().ok_or(CatalogViewStoreError::MissingParent)?;
        fs::create_dir_all(parent)?;
        apply_migrations(&path, &VIEW_MIGRATIONS)?;
        Ok(Self { path })
    }

    pub fn load(&self) -> Result<Option<CatalogViewState>, CatalogViewStoreError> {
        let connection = self.connection()?;
        let raw = connection
            .query_row(SELECT_VIEW, [], |row| {
                Ok(RawCatalogView {
                    query: row.get(0)?,
                    sort: row.get(1)?,
                    page: row.get(2)?,
                    selected_product_id: row.get(3)?,
                    active_category: row.get(4)?,
                    product_scroll_top: row.get(5)?,
                    relation_scroll_top: RelationValues {
                        selection: row.get(6)?,
                        additional: row.get(7)?,
                        construction: row.get(8)?,
                    },
                    relation_query: RelationValues {
                        selection: row.get(9)?,
                        additional: row.get(10)?,
                        construction: row.get(11)?,
                    },
                    relation_page: RelationValues {
                        selection: row.get(12)?,
                        additional: row.get(13)?,
                        construction: row.get(14)?,
                    },
                })
            })
            .optional()?;
        raw.map(CatalogViewState::try_from).transpose()
    }

    pub fn save(&self, state: &CatalogViewState) -> Result<(), CatalogViewStoreError> {
        state.validate()?;
        let connection = self.connection()?;
        connection.execute(
            UPSERT_VIEW,
            params![
                &state.query,
                sort_name(state.sort),
                i64::from(state.page),
                &state.selected_product_id,
                category_name(state.active_category),
                state.product_scroll_top,
                state.relation_scroll_top.selection,
                state.relation_scroll_top.additional,
                state.relation_scroll_top.construction,
                &state.relation_query.selection,
                &state.relation_query.additional,
                &state.relation_query.construction,
                i64::from(state.relation_page.selection),
                i64::from(state.relation_page.additional),
                i64::from(state.relation_page.construction),
            ],
        )?;
        Ok(())
    }

    fn connection(&self) -> Result<Connection, rusqlite::Error> {
        let connection = Connection::open(&self.path)?;
        connection.busy_timeout(Duration::from_secs(5))?;
        Ok(connection)
    }
}

#[derive(Debug)]
struct RawCatalogView {
    query: String,
    sort: String,
    page: i64,
    selected_product_id: Option<String>,
    active_category: String,
    product_scroll_top: f64,
    relation_scroll_top: RelationValues<f64>,
    relation_query: RelationValues<String>,
    relation_page: RelationValues<i64>,
}

impl CatalogViewState {
    /// Validates page and scroll values before durable storage.
    ///
    /// # Errors
    ///
    /// Returns an error when a page is zero or a scroll position is negative or non-finite.
    pub(crate) fn validate(&self) -> Result<(), CatalogViewStoreError> {
        if self.page == 0
            || self.relation_page.selection == 0
            || self.relation_page.additional == 0
            || self.relation_page.construction == 0
        {
            return Err(CatalogViewStoreError::InvalidState(
                "catalog pages must be at least one",
            ));
        }
        for scroll_top in [
            self.product_scroll_top,
            self.relation_scroll_top.selection,
            self.relation_scroll_top.additional,
            self.relation_scroll_top.construction,
        ] {
            if !scroll_top.is_finite() || scroll_top < 0.0 {
                return Err(CatalogViewStoreError::InvalidState(
                    "scroll positions must be finite and non-negative",
                ));
            }
        }
        Ok(())
    }
}

impl TryFrom<RawCatalogView> for CatalogViewState {
    type Error = CatalogViewStoreError;

    fn try_from(raw: RawCatalogView) -> Result<Self, Self::Error> {
        let state = Self {
            query: raw.query,
            sort: parse_sort(&raw.sort)?,
            page: parse_page(raw.page)?,
            selected_product_id: raw.selected_product_id,
            active_category: parse_category(&raw.active_category)?,
            product_scroll_top: raw.product_scroll_top,
            relation_scroll_top: raw.relation_scroll_top,
            relation_query: raw.relation_query,
            relation_page: RelationValues {
                selection: parse_page(raw.relation_page.selection)?,
                additional: parse_page(raw.relation_page.additional)?,
                construction: parse_page(raw.relation_page.construction)?,
            },
        };
        state.validate()?;
        Ok(state)
    }
}

fn parse_page(value: i64) -> Result<u32, CatalogViewStoreError> {
    u32::try_from(value).map_err(|_| CatalogViewStoreError::NumericRange)
}

const fn sort_name(sort: CatalogSort) -> &'static str {
    match sort {
        CatalogSort::PriceAsc => "price_asc",
        CatalogSort::PriceDesc => "price_desc",
        CatalogSort::NameAsc => "name_asc",
        CatalogSort::ProductIdAsc => "product_id_asc",
    }
}

fn parse_sort(value: &str) -> Result<CatalogSort, CatalogViewStoreError> {
    match value {
        "price_asc" => Ok(CatalogSort::PriceAsc),
        "price_desc" => Ok(CatalogSort::PriceDesc),
        "name_asc" => Ok(CatalogSort::NameAsc),
        "product_id_asc" => Ok(CatalogSort::ProductIdAsc),
        unsupported => Err(CatalogViewStoreError::UnsupportedSort(
            unsupported.to_owned(),
        )),
    }
}

const fn category_name(category: RelationCategory) -> &'static str {
    match category {
        RelationCategory::Selection => "selection",
        RelationCategory::Additional => "additional",
        RelationCategory::Construction => "construction",
    }
}

fn parse_category(value: &str) -> Result<RelationCategory, CatalogViewStoreError> {
    match value {
        "selection" => Ok(RelationCategory::Selection),
        "additional" => Ok(RelationCategory::Additional),
        "construction" => Ok(RelationCategory::Construction),
        unsupported => Err(CatalogViewStoreError::UnsupportedCategory(
            unsupported.to_owned(),
        )),
    }
}
