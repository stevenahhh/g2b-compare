use serde::{Deserialize, Serialize};

pub const CATALOG_PAGE_SIZE: u64 = 30;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CatalogSort {
    PriceAsc,
    PriceDesc,
    NameAsc,
    ProductIdAsc,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RelationCategory {
    Selection,
    Additional,
    Construction,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RelationKind {
    Additional,
    Component,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CatalogProduct {
    pub product_id: String,
    pub name: String,
    pub spec: String,
    pub company_name: String,
    pub unit: String,
    pub price_won: i64,
    pub contract_method: String,
    pub delivery_condition: String,
    pub delivery_days: String,
    pub contract_end_date: String,
    pub image_url: String,
    pub detail_url: String,
    pub g2b_url: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CatalogOption {
    pub parent_product_id: String,
    pub parent_name: String,
    pub relation_id: String,
    pub relation_kind: RelationKind,
    pub category: RelationCategory,
    pub product_id: String,
    pub name: String,
    pub spec: String,
    pub unit: String,
    pub price_won: i64,
    pub company_name: String,
    pub detail_url: String,
    pub g2b_url: String,
    pub image_url: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CatalogPage<T> {
    pub items: Vec<T>,
    pub page: u32,
    pub page_count: u64,
    pub total_count: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ProductSearchRequest {
    pub company_name: String,
    pub query: String,
    pub sort: CatalogSort,
    pub page: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RelationSearchRequest {
    pub query: String,
    pub sort: CatalogSort,
    pub page: u32,
    pub parent_product_id: String,
    pub category: RelationCategory,
    pub company_name: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CatalogLineKind {
    Main,
    Option,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AddCatalogItemRequest {
    pub product_id: String,
    pub line_kind: CatalogLineKind,
    pub parent_product_id: Option<String>,
    pub relation_id: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AddCatalogItemResult {
    pub estimate_id: String,
    pub line_count: u64,
    pub revision: i64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RelationValues<T> {
    pub selection: T,
    pub additional: T,
    pub construction: T,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct CatalogViewState {
    pub query: String,
    pub sort: CatalogSort,
    pub page: u32,
    pub selected_product_id: Option<String>,
    pub active_category: RelationCategory,
    pub product_scroll_top: f64,
    pub relation_scroll_top: RelationValues<f64>,
    pub relation_query: RelationValues<String>,
    pub relation_page: RelationValues<u32>,
}
