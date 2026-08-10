use std::{
    collections::BTreeSet,
    io::Read,
    path::{Path, PathBuf},
    sync::{Arc, Condvar, Mutex, PoisonError},
    time::Duration,
};

use reqwest::blocking::Client;
use rusqlite::{Connection, OpenFlags, OptionalExtension, params};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Emitter, State};
use thiserror::Error;
use time::{
    Date, Duration as TimeDuration, OffsetDateTime, format_description::well_known::Rfc3339,
};

use crate::{
    db::advance_catalog_cache_version,
    remote::{EmbeddedApiKey, embedded_api_key},
};

const OFFICIAL_SYNC_SCHEME: &str = "https";
const OFFICIAL_SYNC_HOST: &str = "apis.data.go.kr";
const OFFICIAL_SYNC_PATH: &str =
    "/1230000/at/ShoppingMallPrdctInfoService/getShoppingMallPrdctInfoList";
const OFFICIAL_SYNC_URL: &str =
    "https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService/getShoppingMallPrdctInfoList";
const CONNECT_TIMEOUT: Duration = Duration::from_secs(5);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(30);
const MAX_RESPONSE_BYTES: u64 = 1_048_576;
const MAX_PROVIDER_PAGE_ROWS: u32 = 10;
const DATA_SYNC_STATUS_EVENT: &str = "data-sync-status";
const SERVICE_KEY_PARAMETER: &str = "serviceKey";
const SHOPPING_MALL_OPERATION: &str = "getShoppingMallPrdctInfoList";
const DESKTOP_SYNC_CHECKPOINT: &str = "__desktop_official_sync__";
const SHOP_HOME: &str = "https://shop.g2b.go.kr/";
const REQUIRED_PRODUCT_FIELDS: &[&str] = &[
    "cntrctBgnDate",
    "cntrctCorpBizno",
    "cntrctCorpNm",
    "cntrctDate",
    "cntrctDeptNm",
    "cntrctEndDate",
    "cntrctMthdNm",
    "cntrctPrceAmt",
    "dlvrTmlmtDaynum",
    "dtilPrdctClsfcNo",
    "dtilPrdctClsfcNoNm",
    "entrprsDivNm",
    "exclncPrcrmntPrdctYn",
    "masYn",
    "prdctClsfcNo",
    "prdctClsfcNoNm",
    "prdctDlvrPlceNm",
    "prdctDlvryCndtnNm",
    "prdctIdntNo",
    "prdctImgUrl",
    "prdctLrgclsfcCd",
    "prdctLrgclsfcNm",
    "prdctMakrNm",
    "prdctMidclsfcCd",
    "prdctMidclsfcNm",
    "prdctSpecNm",
    "prdctSplyRgnNm",
    "prdctUnit",
    "prodctCertList",
    "rgstDt",
    "shopngCntrctNo",
    "shopngCntrctSno",
    "smetprCmptProdctYn",
];
const COUNTS_SQL: &str = "
WITH source_operations(operation) AS (
    VALUES
        ('getMASCntrctPrdctInfoList'),
        ('getUcntrctPrdctInfoList'),
        ('getThptyUcntrctPrdctInfoList')
)
SELECT
    (SELECT COUNT(*) FROM priority_companies),
    (SELECT COUNT(*) FROM priority_products),
    (
        SELECT CASE
            WHEN (SELECT COUNT(*) FROM priority_contract_options) > 0
                THEN (SELECT COUNT(*) FROM priority_contract_options)
            WHEN (SELECT COUNT(*) FROM verified_product_options) > 0
                THEN (SELECT COUNT(*) FROM verified_product_options)
            ELSE (SELECT COUNT(*) FROM priority_product_options)
        END
    ),
    (SELECT COUNT(*) FROM priority_options),
    (SELECT COUNT(DISTINCT product_id) FROM priority_options),
    (
        SELECT COUNT(*)
        FROM priority_companies AS company
        CROSS JOIN source_operations AS operation
        LEFT JOIN priority_crawl_state AS state
          ON state.company_name = company.name
         AND state.operation = operation.operation
        WHERE COALESCE(state.complete, 0) = 0
    ),
    (SELECT COUNT(*) FROM priority_products WHERE site_crawled_at = '')
";

/// The JSON event emitted whenever an explicit data synchronization changes stage.
pub const DATA_SYNC_EVENT: &str = DATA_SYNC_STATUS_EVENT;

/// The seven persisted collection counts used by the legacy data-status endpoint.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct DataCounts {
    pub company_count: u64,
    pub product_count: u64,
    pub relation_count: u64,
    pub option_row_count: u64,
    pub unique_option_count: u64,
    pub pending_api_target_count: u64,
    pub pending_site_product_count: u64,
}

/// Local data availability and the most recently retained status error.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct DataStatus {
    #[serde(flatten)]
    pub counts: DataCounts,
    pub ready: bool,
    pub readiness: String,
    pub error: Option<String>,
}

impl PartialEq for DataStatus {
    fn eq(&self, other: &Self) -> bool {
        self.counts == other.counts
            && self.ready == other.ready
            && self.readiness == other.readiness
    }
}

impl Eq for DataStatus {}

impl DataStatus {
    /// Builds a ready or empty status from persisted counts.
    #[must_use]
    pub fn from_counts(counts: DataCounts) -> Self {
        let ready = counts.product_count > 0;
        Self {
            counts,
            ready,
            readiness: if ready { "ready" } else { "empty" }.to_owned(),
            error: None,
        }
    }

    /// Retains these known-good values while recording only a public failure code.
    #[must_use]
    pub fn retain_on_refresh_failure(&self, error: &DiagnosticError) -> Self {
        let mut retained = self.clone();
        retained.error = Some(error.public_code());
        retained
    }
}

/// Public, credential-safe failures produced by local and remote data operations.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum DiagnosticError {
    #[error("data-unavailable")]
    DataUnavailable,
    #[error("transport-unavailable")]
    TransportUnavailable,
    #[error("response-too-large")]
    ResponseTooLarge,
    #[error("provider-response-invalid")]
    ProviderResponseInvalid,
    #[error("HTTP {0}")]
    ProviderStatus(u16),
}

impl DiagnosticError {
    /// Drops private implementation details in favor of the stable unavailable-data code.
    #[must_use]
    pub const fn data_unavailable(_private_detail: &str) -> Self {
        Self::DataUnavailable
    }

    /// Returns the renderer-safe code or HTTP status summary.
    #[must_use]
    pub fn public_code(&self) -> String {
        match self {
            Self::DataUnavailable => "data-unavailable".to_owned(),
            Self::TransportUnavailable => "transport-unavailable".to_owned(),
            Self::ResponseTooLarge => "response-too-large".to_owned(),
            Self::ProviderResponseInvalid => "provider-response-invalid".to_owned(),
            Self::ProviderStatus(status_code) => format!("HTTP {status_code}"),
        }
    }
}

/// One of the legacy manual synchronization stages, in pipeline order.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum SyncStage {
    Sync,
    ImportRelations,
    Materialize,
    RebuildIndex,
    Precompute,
}

impl SyncStage {
    const ALL: [Self; 5] = [
        Self::Sync,
        Self::ImportRelations,
        Self::Materialize,
        Self::RebuildIndex,
        Self::Precompute,
    ];
}

/// The serialized state of one explicit synchronization request.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SyncStatus {
    pub state: String,
    pub stage: Option<SyncStage>,
    pub error: Option<String>,
}

impl SyncStatus {
    /// Constructs a running status at an exact legacy stage.
    #[must_use]
    pub fn running(stage: SyncStage) -> Self {
        Self {
            state: "running".to_owned(),
            stage: Some(stage),
            error: None,
        }
    }

    /// Constructs a successfully completed status.
    #[must_use]
    pub fn complete() -> Self {
        Self {
            state: "complete".to_owned(),
            stage: None,
            error: None,
        }
    }

    /// Constructs a failed status from an already sanitized error message.
    #[must_use]
    pub fn failed(stage: SyncStage, error: impl Into<String>) -> Self {
        Self {
            state: "failed".to_owned(),
            stage: Some(stage),
            error: Some(error.into()),
        }
    }
}

/// Result of the explicit connectivity and local-storage diagnostic command.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct DataDiagnosticResult {
    pub state: String,
    pub checked_at: String,
    pub code: Option<String>,
}

impl DataDiagnosticResult {
    fn passed() -> Self {
        Self {
            state: "passed".to_owned(),
            checked_at: current_timestamp(),
            code: None,
        }
    }

    fn warning(error: DiagnosticError) -> Self {
        Self {
            state: "warning".to_owned(),
            checked_at: current_timestamp(),
            code: Some(error.public_code()),
        }
    }

    fn failed(error: DiagnosticError) -> Self {
        Self {
            state: "failed".to_owned(),
            checked_at: current_timestamp(),
            code: Some(error.public_code()),
        }
    }
}

/// The fixed official HTTPS endpoint accepted by the Rust-only transport boundary.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OfficialSyncEndpoint {
    scheme: &'static str,
    host: &'static str,
    path: &'static str,
    url: &'static str,
}

impl OfficialSyncEndpoint {
    /// Returns the fixed official hostname.
    #[must_use]
    pub const fn host(self) -> &'static str {
        self.host
    }

    /// Returns the fixed provider path.
    #[must_use]
    pub const fn path(self) -> &'static str {
        self.path
    }

    /// Returns whether the endpoint is HTTPS.
    #[must_use]
    pub const fn is_https(self) -> bool {
        matches!(self.scheme.as_bytes(), [b'h', b't', b't', b'p', b's'])
    }

    /// Returns the immutable full endpoint URL.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        self.url
    }
}

/// Returns the only endpoint a data diagnostic or sync operation may contact.
#[must_use]
pub const fn official_sync_endpoint() -> OfficialSyncEndpoint {
    OfficialSyncEndpoint {
        scheme: OFFICIAL_SYNC_SCHEME,
        host: OFFICIAL_SYNC_HOST,
        path: OFFICIAL_SYNC_PATH,
        url: OFFICIAL_SYNC_URL,
    }
}

/// Removes provider response content and credentials from a visible diagnostic.
#[must_use]
pub fn sanitize_diagnostic(
    status_code: u16,
    _provider_body: &str,
    _credentials: &[&str],
) -> String {
    format!("HTTP {status_code}")
}

/// A fixed-host request incapable of accepting renderer-supplied URLs or parameters.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OfficialDataRequest {
    endpoint: OfficialSyncEndpoint,
    page_number: u32,
    inquiry_date: String,
}

impl OfficialDataRequest {
    /// Returns the immutable endpoint selected by this request.
    #[must_use]
    pub const fn endpoint(&self) -> OfficialSyncEndpoint {
        self.endpoint
    }

    /// Returns the fixed, bounded page requested from the official endpoint.
    #[must_use]
    pub const fn page_number(&self) -> u32 {
        self.page_number
    }
}

/// A bounded official response retained only until the trusted parser has consumed it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderResponse {
    status_code: u16,
    body: Vec<u8>,
}

impl ProviderResponse {
    /// Creates a status-only response fixture for diagnostics that do not consume a body.
    #[must_use]
    pub const fn new(status_code: u16) -> Self {
        Self {
            status_code,
            body: Vec::new(),
        }
    }

    /// Creates a bounded JSON fixture for an injected official transport.
    #[must_use]
    pub fn from_json(status_code: u16, body: impl Into<Vec<u8>>) -> Self {
        Self {
            status_code,
            body: body.into(),
        }
    }

    /// Returns the received HTTP status code.
    #[must_use]
    pub const fn status_code(&self) -> u16 {
        self.status_code
    }

    const fn is_success(&self) -> bool {
        self.status_code >= 200 && self.status_code < 300
    }

    fn body(&self) -> &[u8] {
        &self.body
    }
}

/// Credential-safe errors emitted by an official provider transport.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum TransportError {
    #[error("transport-unavailable")]
    Unavailable,
    #[error("response-too-large")]
    ResponseTooLarge,
    #[error("provider-response-invalid")]
    ProviderResponseInvalid,
}

impl From<TransportError> for DiagnosticError {
    fn from(value: TransportError) -> Self {
        match value {
            TransportError::Unavailable => Self::TransportUnavailable,
            TransportError::ResponseTooLarge => Self::ResponseTooLarge,
            TransportError::ProviderResponseInvalid => Self::ProviderResponseInvalid,
        }
    }
}

/// Injectable HTTPS transport used only for the fixed official data request.
pub trait OfficialDataTransport: Send + Sync + 'static {
    /// Executes one fixed-endpoint request with the Rust-only embedded credential.
    ///
    /// # Errors
    ///
    /// Returns a credential-safe transport error without retaining provider content.
    fn execute(
        &self,
        request: OfficialDataRequest,
        credential: EmbeddedApiKey,
    ) -> Result<ProviderResponse, TransportError>;
}

#[derive(Default)]
struct ReqwestOfficialDataTransport;

impl OfficialDataTransport for ReqwestOfficialDataTransport {
    fn execute(
        &self,
        request: OfficialDataRequest,
        credential: EmbeddedApiKey,
    ) -> Result<ProviderResponse, TransportError> {
        let client = Client::builder()
            .https_only(true)
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(CONNECT_TIMEOUT)
            .timeout(REQUEST_TIMEOUT)
            .build()
            .map_err(|_| TransportError::Unavailable)?;
        let parameters = [
            (
                SERVICE_KEY_PARAMETER,
                credential.expose_for_transport().to_owned(),
            ),
            ("type", "json".to_owned()),
            ("pageNo", request.page_number().to_string()),
            ("numOfRows", MAX_PROVIDER_PAGE_ROWS.to_string()),
            ("inqryDiv", "1".to_owned()),
            ("inqryBgnDate", request.inquiry_date.clone()),
            ("inqryEndDate", request.inquiry_date.clone()),
        ];
        let mut response = client
            .get(request.endpoint().as_str())
            .query(&parameters)
            .send()
            .map_err(|_| TransportError::Unavailable)?;
        let status_code = response.status().as_u16();
        let mut body = Vec::new();
        response
            .by_ref()
            .take(MAX_RESPONSE_BYTES.saturating_add(1))
            .read_to_end(&mut body)
            .map_err(|_| TransportError::Unavailable)?;
        if u64::try_from(body.len()).map_err(|_| TransportError::ResponseTooLarge)?
            > MAX_RESPONSE_BYTES
        {
            return Err(TransportError::ResponseTooLarge);
        }
        if (200..300).contains(&status_code) && !is_successful_provider_payload(&body) {
            return Err(TransportError::ProviderResponseInvalid);
        }
        Ok(ProviderResponse { status_code, body })
    }
}

/// A synchronous, injected implementation of one data synchronization stage.
pub trait DataSyncRunner: Send + Sync + 'static {
    /// Runs one stage without exposing provider payloads or credentials.
    ///
    /// # Errors
    ///
    /// Returns only a renderer-safe failure code or HTTP status summary.
    fn run_stage(&self, stage: SyncStage) -> Result<(), DiagnosticError>;

    /// Discards a failed in-progress publication, if this runner owns one.
    fn abort(&self) {}
}

#[derive(Clone)]
struct ValidatedCatalogRecord {
    product_id: String,
    contract_number: String,
    contract_sequence: String,
    category_number: String,
    category_name: String,
    detail_category_number: String,
    spec: String,
    company_name: String,
    unit: String,
    price_won: i64,
    contract_method: String,
    delivery_condition: String,
    delivery_days: String,
    contract_end_date: String,
    image_url: String,
    detail_url: String,
    raw_json: String,
}

struct ParsedProviderPage {
    page_number: u32,
    page_size: u32,
    total_count: u32,
    request_fingerprint: String,
    records: Vec<ValidatedCatalogRecord>,
}

struct PendingSync {
    page: ParsedProviderPage,
    observed_at: String,
    publication: Option<Vec<ValidatedCatalogRecord>>,
    connection: Option<Connection>,
    staged: bool,
    published: bool,
}

struct OfficialDataSyncRunner {
    database: PathBuf,
    transport: Arc<dyn OfficialDataTransport>,
    pending: Mutex<Option<PendingSync>>,
}

impl OfficialDataSyncRunner {
    fn new(database: PathBuf, transport: Arc<dyn OfficialDataTransport>) -> Self {
        Self {
            database,
            transport,
            pending: Mutex::new(None),
        }
    }

    fn fetch_and_validate(&self) -> Result<(), DiagnosticError> {
        self.abort();
        let credential = embedded_api_key().ok_or(DiagnosticError::TransportUnavailable)?;
        let request = official_data_request(next_sync_page(&self.database)?);
        let response = self
            .transport
            .execute(request.clone(), credential)
            .map_err(DiagnosticError::from)?;
        if !response.is_success() {
            return Err(DiagnosticError::ProviderStatus(response.status_code()));
        }
        let page = parse_provider_page(response.body(), &request)?;
        let observed_at = current_timestamp();
        *recover_lock(self.pending.lock()) = Some(PendingSync {
            page,
            observed_at,
            publication: None,
            connection: None,
            staged: false,
            published: false,
        });
        Ok(())
    }

    fn import_relations(&self) -> Result<(), DiagnosticError> {
        (|| {
            let mut pending = recover_lock(self.pending.lock());
            let session = pending.as_mut().ok_or(DiagnosticError::DataUnavailable)?;
            let mut offer_keys = BTreeSet::new();
            for record in &session.page.records {
                let offer_key = format!("{}:{}", record.contract_number, record.contract_sequence);
                if !offer_keys.insert(offer_key) {
                    return Err(DiagnosticError::ProviderResponseInvalid);
                }
            }
            session.publication = Some(session.page.records.clone());
            drop(pending);
            Ok(())
        })()
    }

    fn stage_materialization(&self) -> Result<(), DiagnosticError> {
        (|| {
            let mut pending = recover_lock(self.pending.lock());
            let session = pending.as_mut().ok_or(DiagnosticError::DataUnavailable)?;
            let publication = session
                .publication
                .as_deref()
                .ok_or(DiagnosticError::DataUnavailable)?;
            if session.connection.is_some() || session.staged {
                return Err(DiagnosticError::DataUnavailable);
            }
            let connection = open_sync_database(&self.database)?;
            connection
                .execute_batch("BEGIN IMMEDIATE;")
                .map_err(|_| DiagnosticError::DataUnavailable)?;
            if let Err(error) =
                stage_catalog_records(&connection, publication, &session.observed_at)
            {
                let _ = connection.execute_batch("ROLLBACK;");
                return Err(error);
            }
            session.connection = Some(connection);
            session.staged = true;
            drop(pending);
            Ok(())
        })()
    }

    fn publish_and_rebuild_index(&self) -> Result<(), DiagnosticError> {
        (|| {
            let mut pending = recover_lock(self.pending.lock());
            let session = pending.as_mut().ok_or(DiagnosticError::DataUnavailable)?;
            if !session.staged || session.published {
                return Err(DiagnosticError::DataUnavailable);
            }
            let connection = session
                .connection
                .as_ref()
                .ok_or(DiagnosticError::DataUnavailable)?;
            publish_staged_catalog(connection)?;
            session.published = true;
            drop(pending);
            Ok(())
        })()
    }

    fn checkpoint_and_commit(&self) -> Result<(), DiagnosticError> {
        let mut pending = recover_lock(self.pending.lock());
        let result = (|| {
            let session = pending.as_mut().ok_or(DiagnosticError::DataUnavailable)?;
            if !session.staged || !session.published {
                return Err(DiagnosticError::DataUnavailable);
            }
            let connection = session
                .connection
                .as_ref()
                .ok_or(DiagnosticError::DataUnavailable)?;
            write_sync_checkpoint(connection, &session.page, &session.observed_at)?;
            advance_catalog_cache_version(connection)
                .map_err(|_| DiagnosticError::DataUnavailable)?;
            let _counts = read_data_counts_from_connection(connection)?;
            connection
                .execute_batch("COMMIT;")
                .map_err(|_| DiagnosticError::DataUnavailable)
        })();
        if result.is_ok() {
            *pending = None;
        }
        result
    }
}

impl DataSyncRunner for OfficialDataSyncRunner {
    fn run_stage(&self, stage: SyncStage) -> Result<(), DiagnosticError> {
        let result = match stage {
            SyncStage::Sync => self.fetch_and_validate(),
            SyncStage::ImportRelations => self.import_relations(),
            SyncStage::Materialize => self.stage_materialization(),
            SyncStage::RebuildIndex => self.publish_and_rebuild_index(),
            SyncStage::Precompute => self.checkpoint_and_commit(),
        };
        if result.is_err() {
            self.abort();
        }
        result
    }

    fn abort(&self) {
        if let Some(mut session) = recover_lock(self.pending.lock()).take()
            && let Some(connection) = session.connection.take()
        {
            let _ = connection.execute_batch("ROLLBACK;");
        }
    }
}

fn open_sync_database(database: &Path) -> Result<Connection, DiagnosticError> {
    let connection = Connection::open(database).map_err(|_| DiagnosticError::DataUnavailable)?;
    connection
        .busy_timeout(Duration::from_secs(5))
        .map_err(|_| DiagnosticError::DataUnavailable)?;
    connection
        .pragma_update(None, "foreign_keys", true)
        .map_err(|_| DiagnosticError::DataUnavailable)?;
    Ok(connection)
}

fn next_sync_page(database: &Path) -> Result<u32, DiagnosticError> {
    let connection = Connection::open_with_flags(
        database,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|_| DiagnosticError::DataUnavailable)?;
    connection
        .pragma_update(None, "query_only", true)
        .map_err(|_| DiagnosticError::DataUnavailable)?;
    let checkpoint = connection
        .query_row(
            "SELECT next_page, complete FROM priority_crawl_state
             WHERE company_name = ?1 AND operation = ?2",
            params![DESKTOP_SYNC_CHECKPOINT, SHOPPING_MALL_OPERATION],
            |row| Ok((row.get::<_, i64>(0)?, row.get::<_, i64>(1)?)),
        )
        .optional()
        .map_err(|_| DiagnosticError::DataUnavailable)?;
    let Some((next_page, complete)) = checkpoint else {
        return Ok(1);
    };
    if !matches!(complete, 0 | 1) {
        return Err(DiagnosticError::DataUnavailable);
    }
    if complete == 1 {
        return Ok(1);
    }
    let page = u32::try_from(next_page).map_err(|_| DiagnosticError::DataUnavailable)?;
    if page == 0 {
        return Err(DiagnosticError::DataUnavailable);
    }
    Ok(page)
}

const STAGING_TABLES_SQL: &str = "CREATE TEMP TABLE desktop_sync_stage_products (
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
    observed_at TEXT NOT NULL
);
CREATE TEMP TABLE desktop_sync_stage_offers (
    operation TEXT NOT NULL,
    offer_key TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    price_won INTEGER NOT NULL,
    unit TEXT NOT NULL,
    contract_method TEXT NOT NULL,
    delivery_condition TEXT NOT NULL,
    delivery_days TEXT NOT NULL,
    contract_end_date TEXT NOT NULL,
    image_url TEXT NOT NULL,
    detail_url TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    active INTEGER NOT NULL
);";

const STAGE_PRODUCT_SQL: &str = "INSERT INTO desktop_sync_stage_products VALUES
(?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18, ?19)
ON CONFLICT(product_id) DO UPDATE SET
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
    observed_at=excluded.observed_at";

const STAGE_OFFER_SQL: &str = "INSERT INTO desktop_sync_stage_offers VALUES
(?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15)";

fn stage_catalog_records(
    connection: &Connection,
    records: &[ValidatedCatalogRecord],
    observed_at: &str,
) -> Result<(), DiagnosticError> {
    connection
        .execute_batch(STAGING_TABLES_SQL)
        .map_err(|_| DiagnosticError::DataUnavailable)?;
    let mut products = connection
        .prepare(STAGE_PRODUCT_SQL)
        .map_err(|_| DiagnosticError::DataUnavailable)?;
    let mut offers = connection
        .prepare(STAGE_OFFER_SQL)
        .map_err(|_| DiagnosticError::DataUnavailable)?;
    for record in records {
        products
            .execute(params![
                record.product_id,
                SHOPPING_MALL_OPERATION,
                record.contract_number,
                record.contract_sequence,
                record.category_number,
                record.category_name,
                record.detail_category_number,
                record.spec,
                record.company_name,
                record.unit,
                record.price_won,
                record.contract_method,
                record.delivery_condition,
                record.delivery_days,
                record.contract_end_date,
                record.image_url,
                record.detail_url,
                record.raw_json,
                observed_at,
            ])
            .map_err(|_| DiagnosticError::DataUnavailable)?;
        offers
            .execute(params![
                SHOPPING_MALL_OPERATION,
                format!("{}:{}", record.contract_number, record.contract_sequence),
                record.product_id,
                record.company_name,
                record.price_won,
                record.unit,
                record.contract_method,
                record.delivery_condition,
                record.delivery_days,
                record.contract_end_date,
                record.image_url,
                record.detail_url,
                record.raw_json,
                observed_at,
                1_i64,
            ])
            .map_err(|_| DiagnosticError::DataUnavailable)?;
    }
    Ok(())
}

fn publish_staged_catalog(connection: &Connection) -> Result<(), DiagnosticError> {
    connection
        .execute_batch(
            "INSERT INTO priority_products (
                product_id, operation, contract_number, contract_sequence,
                category_number, category_name, detail_category_number, spec,
                company_name, unit, price_won, contract_method, delivery_condition,
                delivery_days, contract_end_date, image_url, detail_url, raw_json, observed_at
            )
            SELECT product_id, operation, contract_number, contract_sequence,
                   category_number, category_name, detail_category_number, spec,
                   company_name, unit, price_won, contract_method, delivery_condition,
                   delivery_days, contract_end_date, image_url, detail_url, raw_json, observed_at
            FROM desktop_sync_stage_products WHERE true
            ON CONFLICT(product_id) DO UPDATE SET
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
                observed_at=excluded.observed_at;

            INSERT INTO priority_product_offers (
                operation, offer_key, product_id, company_name, price_won, unit,
                contract_method, delivery_condition, delivery_days, contract_end_date,
                image_url, detail_url, raw_json, observed_at, active
            )
            SELECT operation, offer_key, product_id, company_name, price_won, unit,
                   contract_method, delivery_condition, delivery_days, contract_end_date,
                   image_url, detail_url, raw_json, observed_at, active
            FROM desktop_sync_stage_offers WHERE true
            ON CONFLICT(operation, offer_key) DO UPDATE SET
                product_id=excluded.product_id,
                company_name=excluded.company_name,
                price_won=excluded.price_won,
                unit=excluded.unit,
                contract_method=excluded.contract_method,
                delivery_condition=excluded.delivery_condition,
                delivery_days=excluded.delivery_days,
                contract_end_date=excluded.contract_end_date,
                image_url=excluded.image_url,
                detail_url=excluded.detail_url,
                raw_json=excluded.raw_json,
                observed_at=excluded.observed_at,
                active=excluded.active;

            DELETE FROM priority_product_search
            WHERE product_id IN (SELECT product_id FROM desktop_sync_stage_products);
            INSERT INTO priority_product_search (product_id, search_text)
            SELECT product_id, category_name || ' ' || spec || ' ' || company_name || ' ' || product_id
            FROM desktop_sync_stage_products;",
        )
        .map_err(|_| DiagnosticError::DataUnavailable)
}

fn write_sync_checkpoint(
    connection: &Connection,
    page: &ParsedProviderPage,
    observed_at: &str,
) -> Result<(), DiagnosticError> {
    let next_page = page
        .page_number
        .checked_add(1)
        .ok_or(DiagnosticError::ProviderResponseInvalid)?;
    let complete = u64::from(page.page_number)
        .checked_mul(u64::from(page.page_size))
        .is_some_and(|rows| rows >= u64::from(page.total_count));
    connection
        .execute(
            "INSERT INTO priority_crawl_state (company_name, operation, next_page, complete)
             VALUES (?1, ?2, ?3, ?4)
             ON CONFLICT(company_name, operation) DO UPDATE SET
                next_page=excluded.next_page, complete=excluded.complete",
            params![
                DESKTOP_SYNC_CHECKPOINT,
                SHOPPING_MALL_OPERATION,
                i64::from(next_page),
                i64::from(complete),
            ],
        )
        .map_err(|_| DiagnosticError::DataUnavailable)?;
    connection
        .execute(
            "INSERT INTO priority_company_crawl_pages (
                company_name, operation, page_number, page_size, provider_total_count,
                accepted_count, quarantined_count, request_fingerprint, observed_at
            ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, 0, ?7, ?8)
            ON CONFLICT(company_name, operation, page_number) DO UPDATE SET
                page_size=excluded.page_size,
                provider_total_count=excluded.provider_total_count,
                accepted_count=excluded.accepted_count,
                quarantined_count=excluded.quarantined_count,
                request_fingerprint=excluded.request_fingerprint,
                observed_at=excluded.observed_at",
            params![
                DESKTOP_SYNC_CHECKPOINT,
                SHOPPING_MALL_OPERATION,
                i64::from(page.page_number),
                i64::from(page.page_size),
                i64::from(page.total_count),
                i64::try_from(page.records.len()).map_err(|_| DiagnosticError::DataUnavailable)?,
                page.request_fingerprint,
                observed_at,
            ],
        )
        .map_err(|_| DiagnosticError::DataUnavailable)?;
    Ok(())
}

fn parse_provider_page(
    body: &[u8],
    request: &OfficialDataRequest,
) -> Result<ParsedProviderPage, DiagnosticError> {
    if u64::try_from(body.len()).map_err(|_| DiagnosticError::ProviderResponseInvalid)?
        > MAX_RESPONSE_BYTES
    {
        return Err(DiagnosticError::ResponseTooLarge);
    }
    let document = serde_json::from_slice::<Value>(body)
        .map_err(|_| DiagnosticError::ProviderResponseInvalid)?;
    let response = document
        .get("response")
        .and_then(Value::as_object)
        .ok_or(DiagnosticError::ProviderResponseInvalid)?;
    let success = response
        .get("header")
        .and_then(Value::as_object)
        .and_then(|header| header.get("resultCode"))
        .and_then(Value::as_str)
        == Some("00");
    if !success {
        return Err(DiagnosticError::ProviderResponseInvalid);
    }
    let body = response
        .get("body")
        .and_then(Value::as_object)
        .ok_or(DiagnosticError::ProviderResponseInvalid)?;
    let page_number = provider_u32(body.get("pageNo"))?;
    let page_size = provider_u32(body.get("numOfRows"))?;
    let total_count = provider_u32(body.get("totalCount"))?;
    if page_number != request.page_number()
        || page_size == 0
        || page_size > MAX_PROVIDER_PAGE_ROWS
        || total_count == 0
    {
        return Err(DiagnosticError::ProviderResponseInvalid);
    }
    let rows = provider_rows(body.get("items"))?;
    let row_count =
        u64::try_from(rows.len()).map_err(|_| DiagnosticError::ProviderResponseInvalid)?;
    let minimum_total = u64::from(page_number - 1)
        .checked_mul(u64::from(page_size))
        .and_then(|prior_rows| prior_rows.checked_add(row_count))
        .ok_or(DiagnosticError::ProviderResponseInvalid)?;
    if rows.is_empty() || row_count > u64::from(page_size) || minimum_total > u64::from(total_count)
    {
        return Err(DiagnosticError::ProviderResponseInvalid);
    }
    let records = rows
        .into_iter()
        .map(|row| validate_catalog_record(&row))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(ParsedProviderPage {
        page_number,
        page_size,
        total_count,
        request_fingerprint: request_fingerprint(request),
        records,
    })
}

fn provider_u32(value: Option<&Value>) -> Result<u32, DiagnosticError> {
    let Some(value) = value else {
        return Err(DiagnosticError::ProviderResponseInvalid);
    };
    let text = match value {
        Value::Number(number) => number.to_string(),
        Value::String(text) => text.trim().to_owned(),
        _ => return Err(DiagnosticError::ProviderResponseInvalid),
    };
    text.parse::<u32>()
        .map_err(|_| DiagnosticError::ProviderResponseInvalid)
}

fn provider_rows(value: Option<&Value>) -> Result<Vec<Map<String, Value>>, DiagnosticError> {
    let Some(value) = value else {
        return Err(DiagnosticError::ProviderResponseInvalid);
    };
    let value = match value {
        Value::Object(items) if items.contains_key("item") => items
            .get("item")
            .ok_or(DiagnosticError::ProviderResponseInvalid)?,
        other => other,
    };
    match value {
        Value::Array(rows) => rows
            .iter()
            .map(|row| {
                row.as_object()
                    .cloned()
                    .ok_or(DiagnosticError::ProviderResponseInvalid)
            })
            .collect(),
        Value::Object(row) => Ok(vec![row.clone()]),
        Value::String(value) if value.is_empty() => Ok(Vec::new()),
        Value::Null => Ok(Vec::new()),
        _ => Err(DiagnosticError::ProviderResponseInvalid),
    }
}

fn validate_catalog_record(
    row: &Map<String, Value>,
) -> Result<ValidatedCatalogRecord, DiagnosticError> {
    if row
        .values()
        .any(|value| value.is_array() || value.is_object())
        || REQUIRED_PRODUCT_FIELDS
            .iter()
            .any(|field| !row.contains_key(*field))
    {
        return Err(DiagnosticError::ProviderResponseInvalid);
    }
    let product_id = record_text(row, "prdctIdntNo")?;
    let contract_number = record_text(row, "shopngCntrctNo")?;
    let contract_sequence = record_text(row, "shopngCntrctSno")?;
    if !is_product_id(&product_id)
        || contract_number.is_empty()
        || contract_sequence.is_empty()
        || !contract_number
            .bytes()
            .all(|value| value.is_ascii_alphanumeric() || matches!(value, b'_' | b'-'))
    {
        return Err(DiagnosticError::ProviderResponseInvalid);
    }
    let price_won = parse_price(&record_text(row, "cntrctPrceAmt")?)?;
    Ok(ValidatedCatalogRecord {
        product_id,
        detail_url: format!("{SHOP_HOME}link/GMSF001_01/?ctrtItemMngNo={contract_number}"),
        contract_number,
        contract_sequence,
        category_number: record_text(row, "prdctClsfcNo")?,
        category_name: record_text(row, "prdctClsfcNoNm")?,
        detail_category_number: record_text(row, "dtilPrdctClsfcNo")?,
        spec: record_text(row, "prdctSpecNm")?,
        company_name: record_text(row, "cntrctCorpNm")?,
        unit: record_text(row, "prdctUnit")?,
        price_won,
        contract_method: record_text(row, "cntrctMthdNm")?,
        delivery_condition: record_text(row, "prdctDlvryCndtnNm")?,
        delivery_days: record_text(row, "dlvrTmlmtDaynum")?,
        contract_end_date: record_text(row, "cntrctEndDate")?,
        image_url: record_text(row, "prdctImgUrl")?,
        raw_json: serde_json::to_string(row)
            .map_err(|_| DiagnosticError::ProviderResponseInvalid)?,
    })
}

fn record_text(row: &Map<String, Value>, field: &str) -> Result<String, DiagnosticError> {
    let value = row
        .get(field)
        .ok_or(DiagnosticError::ProviderResponseInvalid)?;
    let text = match value {
        Value::String(value) => value.trim().to_owned(),
        Value::Number(value) => value.to_string(),
        Value::Bool(value) => value.to_string(),
        Value::Null => String::new(),
        Value::Array(_) | Value::Object(_) => return Err(DiagnosticError::ProviderResponseInvalid),
    };
    Ok(text)
}

fn parse_price(value: &str) -> Result<i64, DiagnosticError> {
    let normalized = value.replace(',', "");
    let integer = match normalized.split_once('.') {
        Some((integer, fraction))
            if !fraction.is_empty() && fraction.bytes().all(|value| value == b'0') =>
        {
            integer
        }
        Some(_) => return Err(DiagnosticError::ProviderResponseInvalid),
        None => normalized.as_str(),
    };
    if integer.is_empty() || !integer.bytes().all(|value| value.is_ascii_digit()) {
        return Err(DiagnosticError::ProviderResponseInvalid);
    }
    integer
        .parse::<i64>()
        .map_err(|_| DiagnosticError::ProviderResponseInvalid)
}

fn is_product_id(value: &str) -> bool {
    value.len() == 8 && value.bytes().all(|value| value.is_ascii_digit())
}

fn request_fingerprint(request: &OfficialDataRequest) -> String {
    let identity = format!(
        "GET\n{}\npageNo={}\nnumOfRows={}\ninqryDiv=1\ninqryBgnDate={}\ninqryEndDate={}",
        request.endpoint().path(),
        request.page_number(),
        MAX_PROVIDER_PAGE_ROWS,
        request.inquiry_date,
        request.inquiry_date,
    );
    format!("{:x}", Sha256::digest(identity.as_bytes()))
}

/// Observer for deterministic status transitions from one explicit sync request.
pub trait SyncEventSink: Send + Sync {
    /// Publishes the next immutable synchronization state.
    fn publish(&self, status: SyncStatus);
}

struct TauriSyncEventSink {
    app: AppHandle,
}

impl SyncEventSink for TauriSyncEventSink {
    fn publish(&self, status: SyncStatus) {
        let _ = self.app.emit(DATA_SYNC_STATUS_EVENT, status);
    }
}

struct SyncFlight {
    state: Mutex<SyncFlightState>,
    completed: Condvar,
    follower_ready: Condvar,
}

struct SyncFlightState {
    in_flight: bool,
    waiting_followers: usize,
    status: SyncStatus,
}

enum SyncFlightRole {
    Leader,
    Follower(SyncStatus),
}

impl Default for SyncFlight {
    fn default() -> Self {
        Self {
            state: Mutex::new(SyncFlightState {
                in_flight: false,
                waiting_followers: 0,
                status: SyncStatus::complete(),
            }),
            completed: Condvar::new(),
            follower_ready: Condvar::new(),
        }
    }
}

impl SyncFlight {
    fn begin(&self) -> SyncFlightRole {
        let mut state = recover_lock(self.state.lock());
        if state.in_flight {
            state.waiting_followers = state.waiting_followers.saturating_add(1);
            self.follower_ready.notify_all();
            state = recover_lock(
                self.completed
                    .wait_while(state, |current| current.in_flight),
            );
            state.waiting_followers = state.waiting_followers.saturating_sub(1);
            return SyncFlightRole::Follower(state.status.clone());
        }
        state.in_flight = true;
        state.status = SyncStatus::running(SyncStage::Sync);
        SyncFlightRole::Leader
    }

    fn update(&self, status: SyncStatus) {
        recover_lock(self.state.lock()).status = status;
    }

    fn finish(&self, status: SyncStatus) {
        let mut state = recover_lock(self.state.lock());
        state.status = status;
        state.in_flight = false;
        drop(state);
        self.completed.notify_all();
    }

    #[cfg(test)]
    fn wait_for_follower(&self, timeout: Duration) -> bool {
        let (waiting_state, result) = recover_lock(self.follower_ready.wait_timeout_while(
            recover_lock(self.state.lock()),
            timeout,
            |current| current.waiting_followers == 0,
        ));
        let follower_waiting = waiting_state.waiting_followers > 0;
        drop(waiting_state);
        follower_waiting && !result.timed_out()
    }
}

/// Managed local-data state shared by data status, sync, and diagnostics commands.
pub struct DataDiagnosticsState {
    database: PathBuf,
    last_status: Mutex<Option<DataStatus>>,
    transport: Arc<dyn OfficialDataTransport>,
    sync_runner: Arc<dyn DataSyncRunner>,
    sync_flight: SyncFlight,
}

impl DataDiagnosticsState {
    /// Creates the production state around the bootstrapped application database.
    #[must_use]
    pub fn new(database: impl Into<PathBuf>) -> Self {
        let database = database.into();
        let transport: Arc<dyn OfficialDataTransport> = Arc::new(ReqwestOfficialDataTransport);
        let sync_runner: Arc<dyn DataSyncRunner> = Arc::new(OfficialDataSyncRunner::new(
            database.clone(),
            Arc::clone(&transport),
        ));
        Self::with_components(database, transport, sync_runner)
    }

    /// Creates state with injected network and pipeline capabilities for deterministic tests.
    #[must_use]
    pub fn with_components(
        database: impl Into<PathBuf>,
        transport: Arc<dyn OfficialDataTransport>,
        sync_runner: Arc<dyn DataSyncRunner>,
    ) -> Self {
        Self {
            database: database.into(),
            last_status: Mutex::new(None),
            transport,
            sync_runner,
            sync_flight: SyncFlight::default(),
        }
    }

    /// Reads current local counts, retaining the last successful status on an unavailable database.
    ///
    /// # Errors
    ///
    /// Returns `data-unavailable` only when no known-good status can be retained.
    pub fn status(&self) -> Result<DataStatus, DiagnosticError> {
        match read_data_counts(&self.database) {
            Ok(counts) => {
                let status = DataStatus::from_counts(counts);
                *recover_lock(self.last_status.lock()) = Some(status.clone());
                Ok(status)
            }
            Err(error) => recover_lock(self.last_status.lock())
                .as_ref()
                .map_or(Err(error), |status| {
                    Ok(status.retain_on_refresh_failure(&error))
                }),
        }
    }

    /// Runs all legacy stages exactly once, sharing the final status with concurrent callers.
    #[must_use]
    pub fn run_sync(&self, events: &dyn SyncEventSink) -> SyncStatus {
        match self.sync_flight.begin() {
            SyncFlightRole::Follower(status) => status,
            SyncFlightRole::Leader => self.run_sync_as_leader(events),
        }
    }

    /// Performs an explicit remote provider diagnostic without exposing provider content.
    #[must_use]
    pub fn diagnose(&self) -> DataDiagnosticResult {
        if let Err(error) = read_data_counts(&self.database) {
            return DataDiagnosticResult::failed(error);
        }
        let Some(credential) = embedded_api_key() else {
            return DataDiagnosticResult::failed(DiagnosticError::TransportUnavailable);
        };
        match self.transport.execute(official_data_request(1), credential) {
            Ok(response) if response.is_success() => DataDiagnosticResult::passed(),
            Ok(response) => DataDiagnosticResult::warning(DiagnosticError::ProviderStatus(
                response.status_code(),
            )),
            Err(error) => DataDiagnosticResult::warning(DiagnosticError::from(error)),
        }
    }

    fn run_sync_as_leader(&self, events: &dyn SyncEventSink) -> SyncStatus {
        let initial = SyncStatus::running(SyncStage::Sync);
        events.publish(initial);
        for (index, stage) in SyncStage::ALL.into_iter().enumerate() {
            if index > 0 {
                let running = SyncStatus::running(stage);
                self.sync_flight.update(running.clone());
                events.publish(running);
            }
            if let Err(error) = self.sync_runner.run_stage(stage) {
                self.sync_runner.abort();
                let failed = SyncStatus::failed(stage, error.public_code());
                self.sync_flight.finish(failed.clone());
                events.publish(failed.clone());
                return failed;
            }
        }
        let complete = SyncStatus::complete();
        self.sync_flight.finish(complete.clone());
        events.publish(complete.clone());
        complete
    }
}

/// Reads the local bootstrapped status without starting a remote operation.
///
/// # Errors
///
/// Returns a stable unavailable-data error when the production database cannot be read.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn get_data_status(state: State<'_, DataDiagnosticsState>) -> Result<DataStatus, String> {
    state.status().map_err(|error| error.public_code())
}

/// Runs the explicit manual data synchronization through the fixed Rust boundary.
#[must_use]
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn run_data_sync(app: AppHandle, state: State<'_, DataDiagnosticsState>) -> SyncStatus {
    state.run_sync(&TauriSyncEventSink { app })
}

/// Runs a bounded, explicit provider and local-data diagnostic.
#[must_use]
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn run_data_diagnostics(state: State<'_, DataDiagnosticsState>) -> DataDiagnosticResult {
    state.diagnose()
}

fn official_data_request(page_number: u32) -> OfficialDataRequest {
    OfficialDataRequest {
        endpoint: official_sync_endpoint(),
        page_number,
        inquiry_date: compact_provider_date(
            OffsetDateTime::now_utc().date() - TimeDuration::days(1),
        ),
    }
}

fn read_data_counts(database: &Path) -> Result<DataCounts, DiagnosticError> {
    let connection = Connection::open_with_flags(
        database,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|_| DiagnosticError::DataUnavailable)?;
    connection
        .pragma_update(None, "query_only", true)
        .map_err(|_| DiagnosticError::DataUnavailable)?;
    read_data_counts_from_connection(&connection)
}

fn read_data_counts_from_connection(
    connection: &Connection,
) -> Result<DataCounts, DiagnosticError> {
    let values = connection
        .query_row(COUNTS_SQL, [], |row| {
            Ok([
                row.get::<_, i64>(0)?,
                row.get::<_, i64>(1)?,
                row.get::<_, i64>(2)?,
                row.get::<_, i64>(3)?,
                row.get::<_, i64>(4)?,
                row.get::<_, i64>(5)?,
                row.get::<_, i64>(6)?,
            ])
        })
        .map_err(|_| DiagnosticError::DataUnavailable)?;
    let [
        company_count,
        product_count,
        relation_count,
        option_row_count,
        unique_option_count,
        pending_api_target_count,
        pending_site_product_count,
    ] = values;
    Ok(DataCounts {
        company_count: nonnegative_count(company_count)?,
        product_count: nonnegative_count(product_count)?,
        relation_count: nonnegative_count(relation_count)?,
        option_row_count: nonnegative_count(option_row_count)?,
        unique_option_count: nonnegative_count(unique_option_count)?,
        pending_api_target_count: nonnegative_count(pending_api_target_count)?,
        pending_site_product_count: nonnegative_count(pending_site_product_count)?,
    })
}

fn nonnegative_count(value: i64) -> Result<u64, DiagnosticError> {
    u64::try_from(value).map_err(|_| DiagnosticError::DataUnavailable)
}

fn is_successful_provider_payload(body: &[u8]) -> bool {
    serde_json::from_slice::<serde_json::Value>(body).is_ok_and(|value| {
        value
            .pointer("/response/header/resultCode")
            .and_then(serde_json::Value::as_str)
            == Some("00")
    })
}

fn current_timestamp() -> String {
    OffsetDateTime::now_utc()
        .format(&Rfc3339)
        .unwrap_or_else(|_| "0".to_owned())
}

fn compact_provider_date(date: Date) -> String {
    format!(
        "{:04}{:02}{:02}",
        date.year(),
        u8::from(date.month()),
        date.day()
    )
}

fn recover_lock<T>(result: Result<T, PoisonError<T>>) -> T {
    result.unwrap_or_else(PoisonError::into_inner)
}

#[cfg(test)]
mod tests {
    use std::{
        error::Error,
        path::Path,
        sync::{Arc, Mutex},
        thread,
        time::Duration,
    };

    use rusqlite::{Connection, params};
    use serde_json::{Map, Value};

    use crate::db::CatalogCacheStore;
    use tempfile::tempdir;

    use super::{
        DESKTOP_SYNC_CHECKPOINT, DataDiagnosticsState, DataSyncRunner, OfficialDataRequest,
        OfficialDataSyncRunner, OfficialDataTransport, ProviderResponse, SHOPPING_MALL_OPERATION,
        SyncEventSink, SyncFlight, SyncFlightRole, SyncStage, SyncStatus, TransportError,
        is_successful_provider_payload,
    };

    #[test]
    fn provider_success_requires_the_official_machine_consumed_result_code() {
        assert!(is_successful_provider_payload(
            br#"{"response":{"header":{"resultCode":"00"}}}"#,
        ));
        assert!(!is_successful_provider_payload(
            br#"{"response":{"header":{"resultCode":"30"}}}"#,
        ));
        assert!(!is_successful_provider_payload(b"not-json"));
    }

    #[test]
    fn valid_fixture_is_staged_and_published_with_catalog_rows_and_checkpoint()
    -> Result<(), Box<dyn Error>> {
        let temporary = tempdir()?;
        let database = temporary.path().join("catalog.sqlite3");
        create_catalog_schema(&database)?;
        insert_last_good_catalog(&database)?;
        let transport = Arc::new(FixtureTransport::new(ProviderResponse::from_json(
            200,
            valid_payload(1, 1, "12345678"),
        )));
        let state = production_state(&database, Arc::clone(&transport));
        let events = RecordingEvents::default();

        assert_successful_sync(&state, &events, &transport)?;
        let connection = Connection::open(&database)?;
        assert_published_catalog(&connection)?;
        assert_published_checkpoint(&connection)?;
        assert_eq!(
            CatalogCacheStore::open(&database)?.version()?.cache_version,
            2
        );
        assert_eq!(state.status()?.counts.product_count, 2);
        Ok(())
    }

    #[test]
    fn empty_or_invalid_provider_page_never_stages_or_overwrites_last_good_catalog()
    -> Result<(), Box<dyn Error>> {
        let temporary = tempdir()?;
        let database = temporary.path().join("catalog.sqlite3");
        create_catalog_schema(&database)?;
        insert_last_good_catalog(&database)?;
        let transport = Arc::new(FixtureTransport::new(ProviderResponse::from_json(
            200,
            br#"{"response":{"header":{"resultCode":"00"},"body":{"pageNo":1,"numOfRows":10,"totalCount":0,"items":""}}}"#,
        )));
        let state = production_state(&database, transport);

        assert_eq!(
            state.run_sync(&RecordingEvents::default()),
            SyncStatus::failed(SyncStage::Sync, "provider-response-invalid")
        );
        let connection = Connection::open(database)?;
        assert_eq!(
            connection.query_row("SELECT COUNT(*) FROM priority_products", [], |row| {
                row.get::<_, i64>(0)
            })?,
            1
        );
        assert_eq!(
            connection.query_row("SELECT COUNT(*) FROM priority_product_offers", [], |row| {
                row.get::<_, i64>(0)
            },)?,
            1
        );
        assert_eq!(
            connection.query_row(
                "SELECT COUNT(*) FROM priority_crawl_state WHERE company_name = ?1",
                [DESKTOP_SYNC_CHECKPOINT],
                |row| row.get::<_, i64>(0),
            )?,
            0
        );
        Ok(())
    }

    #[test]
    fn publish_failure_rolls_back_staging_rows_indexes_and_checkpoint() -> Result<(), Box<dyn Error>>
    {
        let temporary = tempdir()?;
        let database = temporary.path().join("catalog.sqlite3");
        create_catalog_schema(&database)?;
        insert_last_good_catalog(&database)?;
        let last_good_version = CatalogCacheStore::initialize(&database)?;
        Connection::open(&database)?.execute_batch(
            "CREATE TRIGGER reject_fixture_product
             BEFORE INSERT ON priority_products
             WHEN NEW.product_id = '12345678'
             BEGIN
                SELECT RAISE(ABORT, 'fixture reject');
             END;",
        )?;
        let transport = Arc::new(FixtureTransport::new(ProviderResponse::from_json(
            200,
            valid_payload(1, 1, "12345678"),
        )));
        let state = production_state(&database, transport);

        assert_eq!(
            state.run_sync(&RecordingEvents::default()),
            SyncStatus::failed(SyncStage::RebuildIndex, "data-unavailable")
        );
        let connection = Connection::open(&database)?;
        assert_eq!(
            connection.query_row("SELECT COUNT(*) FROM priority_products", [], |row| {
                row.get::<_, i64>(0)
            })?,
            1
        );
        assert_eq!(
            connection.query_row("SELECT COUNT(*) FROM priority_product_offers", [], |row| {
                row.get::<_, i64>(0)
            },)?,
            1
        );
        assert_eq!(
            connection.query_row(
                "SELECT COUNT(*) FROM priority_product_search WHERE product_id = '12345678'",
                [],
                |row| row.get::<_, i64>(0),
            )?,
            0
        );
        assert_eq!(
            connection.query_row(
                "SELECT COUNT(*) FROM priority_crawl_state WHERE company_name = ?1",
                [DESKTOP_SYNC_CHECKPOINT],
                |row| row.get::<_, i64>(0),
            )?,
            0
        );
        assert_eq!(
            CatalogCacheStore::open(&database)?.version()?,
            last_good_version
        );
        Ok(())
    }

    #[test]
    fn failed_precompute_rolls_back_catalog_publication_and_cache_version()
    -> Result<(), Box<dyn Error>> {
        let temporary = tempdir()?;
        let database = temporary.path().join("catalog.sqlite3");
        create_catalog_schema(&database)?;
        insert_last_good_catalog(&database)?;
        let last_good_version = CatalogCacheStore::initialize(&database)?;
        Connection::open(&database)?.execute_batch(
            "CREATE TRIGGER reject_catalog_cache_advance
             BEFORE UPDATE ON desktop_catalog_cache_state
             BEGIN
                SELECT RAISE(ABORT, 'fixture reject');
             END;",
        )?;
        let transport = Arc::new(FixtureTransport::new(ProviderResponse::from_json(
            200,
            valid_payload(1, 1, "12345678"),
        )));
        let state = production_state(&database, transport);

        assert_eq!(
            state.run_sync(&RecordingEvents::default()),
            SyncStatus::failed(SyncStage::Precompute, "data-unavailable")
        );
        let connection = Connection::open(&database)?;
        assert_eq!(
            connection.query_row(
                "SELECT COUNT(*) FROM priority_products WHERE product_id = '12345678'",
                [],
                |row| row.get::<_, i64>(0),
            )?,
            0
        );
        assert_eq!(
            connection.query_row(
                "SELECT COUNT(*) FROM priority_crawl_state WHERE company_name = ?1",
                [DESKTOP_SYNC_CHECKPOINT],
                |row| row.get::<_, i64>(0),
            )?,
            0
        );
        assert_eq!(
            CatalogCacheStore::open(&database)?.version()?,
            last_good_version
        );
        Ok(())
    }

    #[test]
    fn concurrent_sync_callers_share_the_single_in_flight_result() -> Result<(), Box<dyn Error>> {
        let flight = Arc::new(SyncFlight::default());
        assert!(matches!(flight.begin(), SyncFlightRole::Leader));

        let follower_flight = Arc::clone(&flight);
        let follower = thread::spawn(move || follower_flight.begin());
        assert!(flight.wait_for_follower(Duration::from_secs(1)));

        let expected = SyncStatus::complete();
        flight.finish(expected.clone());
        let result = match follower.join() {
            Ok(SyncFlightRole::Follower(status)) => status,
            Ok(SyncFlightRole::Leader) => {
                return Err("concurrent call became a second leader".into());
            }
            Err(_) => return Err("single-flight follower panicked".into()),
        };
        assert_eq!(result, expected);
        Ok(())
    }

    struct FixtureTransport {
        response: ProviderResponse,
        requests: Mutex<Vec<OfficialDataRequest>>,
    }

    impl FixtureTransport {
        const fn new(response: ProviderResponse) -> Self {
            Self {
                response,
                requests: Mutex::new(Vec::new()),
            }
        }

        fn requests(&self) -> Result<Vec<OfficialDataRequest>, Box<dyn Error>> {
            Ok(self
                .requests
                .lock()
                .map_err(|error| error.to_string())?
                .clone())
        }
    }

    impl OfficialDataTransport for FixtureTransport {
        fn execute(
            &self,
            request: OfficialDataRequest,
            _credential: super::EmbeddedApiKey,
        ) -> Result<ProviderResponse, TransportError> {
            self.requests
                .lock()
                .map_err(|_| TransportError::Unavailable)?
                .push(request);
            Ok(self.response.clone())
        }
    }

    #[derive(Default)]
    struct RecordingEvents {
        statuses: Mutex<Vec<SyncStatus>>,
    }

    impl RecordingEvents {
        fn statuses(&self) -> Result<Vec<SyncStatus>, Box<dyn Error>> {
            Ok(self
                .statuses
                .lock()
                .map_err(|error| error.to_string())?
                .clone())
        }
    }

    impl SyncEventSink for RecordingEvents {
        fn publish(&self, status: SyncStatus) {
            if let Ok(mut statuses) = self.statuses.lock() {
                statuses.push(status);
            }
        }
    }

    fn production_state(database: &Path, transport: Arc<FixtureTransport>) -> DataDiagnosticsState {
        let state_transport: Arc<dyn OfficialDataTransport> = transport.clone();
        let runner_transport: Arc<dyn OfficialDataTransport> = transport;
        let runner: Arc<dyn DataSyncRunner> = Arc::new(OfficialDataSyncRunner::new(
            database.to_path_buf(),
            runner_transport,
        ));
        DataDiagnosticsState::with_components(database, state_transport, runner)
    }

    fn assert_successful_sync(
        state: &DataDiagnosticsState,
        events: &RecordingEvents,
        transport: &FixtureTransport,
    ) -> Result<(), Box<dyn Error>> {
        assert_eq!(state.run_sync(events), SyncStatus::complete());
        assert_eq!(
            events.statuses()?,
            vec![
                SyncStatus::running(SyncStage::Sync),
                SyncStatus::running(SyncStage::ImportRelations),
                SyncStatus::running(SyncStage::Materialize),
                SyncStatus::running(SyncStage::RebuildIndex),
                SyncStatus::running(SyncStage::Precompute),
                SyncStatus::complete(),
            ]
        );
        let requests = transport.requests()?;
        assert_eq!(requests.len(), 1);
        assert_eq!(requests[0].page_number(), 1);
        Ok(())
    }

    fn assert_published_catalog(connection: &Connection) -> Result<(), rusqlite::Error> {
        assert_eq!(
            connection.query_row(
                "SELECT operation, contract_number, contract_sequence, category_name,
                        company_name, price_won, detail_url
                 FROM priority_products WHERE product_id = '12345678'",
                [],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, String>(4)?,
                        row.get::<_, i64>(5)?,
                        row.get::<_, String>(6)?,
                    ))
                },
            )?,
            (
                SHOPPING_MALL_OPERATION.to_owned(),
                "002170306_107".to_owned(),
                "167".to_owned(),
                "Laptop".to_owned(),
                "Fixture Vendor".to_owned(),
                12_500,
                "https://shop.g2b.go.kr/link/GMSF001_01/?ctrtItemMngNo=002170306_107".to_owned(),
            )
        );
        assert_eq!(
            connection.query_row(
                "SELECT product_id, price_won, active FROM priority_product_offers
                 WHERE operation = ?1 AND offer_key = '002170306_107:167'",
                [SHOPPING_MALL_OPERATION],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, i64>(1)?,
                        row.get::<_, i64>(2)?,
                    ))
                },
            )?,
            ("12345678".to_owned(), 12_500, 1)
        );
        assert_eq!(
            connection.query_row(
                "SELECT COUNT(*) FROM priority_product_search WHERE product_id = '12345678'",
                [],
                |row| row.get::<_, i64>(0),
            )?,
            1
        );
        assert_eq!(
            connection.query_row(
                "SELECT category_name FROM priority_products WHERE product_id = '87654321'",
                [],
                |row| row.get::<_, String>(0),
            )?,
            "last-good"
        );
        Ok(())
    }

    fn assert_published_checkpoint(connection: &Connection) -> Result<(), rusqlite::Error> {
        assert_eq!(
            connection.query_row(
                "SELECT next_page, complete FROM priority_crawl_state
                 WHERE company_name = ?1 AND operation = ?2",
                params![DESKTOP_SYNC_CHECKPOINT, SHOPPING_MALL_OPERATION],
                |row| Ok((row.get::<_, i64>(0)?, row.get::<_, i64>(1)?)),
            )?,
            (2, 1)
        );
        assert_eq!(
            connection.query_row(
                "SELECT page_number, page_size, provider_total_count, accepted_count,
                        quarantined_count
                 FROM priority_company_crawl_pages
                 WHERE company_name = ?1 AND operation = ?2",
                params![DESKTOP_SYNC_CHECKPOINT, SHOPPING_MALL_OPERATION],
                |row| {
                    Ok((
                        row.get::<_, i64>(0)?,
                        row.get::<_, i64>(1)?,
                        row.get::<_, i64>(2)?,
                        row.get::<_, i64>(3)?,
                        row.get::<_, i64>(4)?,
                    ))
                },
            )?,
            (1, 10, 1, 1, 0)
        );
        Ok(())
    }

    fn valid_payload(page_number: u32, total_count: u32, product_id: &str) -> Vec<u8> {
        let mut record = Map::new();
        for field in super::REQUIRED_PRODUCT_FIELDS {
            record.insert((*field).to_owned(), Value::String(String::new()));
        }
        for (field, value) in [
            ("cntrctBgnDate", "20260101"),
            ("cntrctCorpBizno", "1234567890"),
            ("cntrctCorpNm", "Fixture Vendor"),
            ("cntrctDate", "20260101"),
            ("cntrctDeptNm", "Fixture Department"),
            ("cntrctEndDate", "20271231"),
            ("cntrctMthdNm", "MAS"),
            ("cntrctPrceAmt", "12,500"),
            ("dlvrTmlmtDaynum", "30"),
            ("dtilPrdctClsfcNo", "4321150301"),
            ("dtilPrdctClsfcNoNm", "Notebook computer"),
            ("entrprsDivNm", "small business"),
            ("exclncPrcrmntPrdctYn", "N"),
            ("masYn", "Y"),
            ("prdctClsfcNo", "43211503"),
            ("prdctClsfcNoNm", "Laptop"),
            ("prdctDlvrPlceNm", "Seoul"),
            ("prdctDlvryCndtnNm", "delivery"),
            ("prdctImgUrl", "https://example.test/product.png"),
            ("prdctLrgclsfcCd", "43"),
            ("prdctLrgclsfcNm", "IT"),
            ("prdctMakrNm", "Fixture Maker"),
            ("prdctMidclsfcCd", "4321"),
            ("prdctMidclsfcNm", "Computers"),
            ("prdctSpecNm", "fixture spec"),
            ("prdctSplyRgnNm", "Korea"),
            ("prdctUnit", "each"),
            ("rgstDt", "20260101"),
            ("shopngCntrctNo", "002170306_107"),
            ("shopngCntrctSno", "167"),
            ("smetprCmptProdctYn", "N"),
        ] {
            record.insert(field.to_owned(), Value::String(value.to_owned()));
        }
        record.insert(
            "prdctIdntNo".to_owned(),
            Value::String(product_id.to_owned()),
        );

        let mut items = Map::new();
        items.insert("item".to_owned(), Value::Array(vec![Value::Object(record)]));
        let mut body = Map::new();
        body.insert("pageNo".to_owned(), Value::from(page_number));
        body.insert("numOfRows".to_owned(), Value::from(10));
        body.insert("totalCount".to_owned(), Value::from(total_count));
        body.insert("items".to_owned(), Value::Object(items));
        let mut header = Map::new();
        header.insert("resultCode".to_owned(), Value::String("00".to_owned()));
        header.insert(
            "resultMsg".to_owned(),
            Value::String("NORMAL SERVICE".to_owned()),
        );
        let mut response = Map::new();
        response.insert("header".to_owned(), Value::Object(header));
        response.insert("body".to_owned(), Value::Object(body));
        let mut document = Map::new();
        document.insert("response".to_owned(), Value::Object(response));
        Value::Object(document).to_string().into_bytes()
    }

    fn create_catalog_schema(path: &Path) -> Result<(), rusqlite::Error> {
        let connection = Connection::open(path)?;
        create_catalog_data_schema(&connection)?;
        create_catalog_sync_schema(&connection)
    }

    fn create_catalog_data_schema(connection: &Connection) -> Result<(), rusqlite::Error> {
        connection.execute_batch(
            "CREATE TABLE priority_companies (
                name TEXT PRIMARY KEY,
                source_row INTEGER NOT NULL,
                location TEXT NOT NULL,
                company_type TEXT NOT NULL,
                declared_product_count INTEGER NOT NULL,
                contract_end_date TEXT NOT NULL
            );
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
            CREATE TABLE priority_product_options (
                parent_product_id TEXT NOT NULL,
                option_product_id TEXT NOT NULL,
                company_name TEXT NOT NULL,
                raw_label TEXT NOT NULL,
                price_won INTEGER NOT NULL,
                PRIMARY KEY (parent_product_id, option_product_id)
            );",
        )?;
        Ok(())
    }

    fn create_catalog_sync_schema(connection: &Connection) -> Result<(), rusqlite::Error> {
        connection.execute_batch(
            "CREATE TABLE priority_contract_options (
                contract_group TEXT NOT NULL,
                relation_id TEXT PRIMARY KEY,
                option_product_id TEXT NOT NULL,
                relation_kind TEXT NOT NULL,
                position INTEGER NOT NULL,
                company_name TEXT NOT NULL,
                raw_label TEXT NOT NULL,
                relation_price_won INTEGER NOT NULL,
                observed_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
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
            CREATE TABLE priority_crawl_state (
                company_name TEXT NOT NULL,
                operation TEXT NOT NULL,
                next_page INTEGER NOT NULL,
                complete INTEGER NOT NULL,
                PRIMARY KEY (company_name, operation)
            );
            CREATE TABLE priority_company_crawl_pages (
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
            CREATE VIRTUAL TABLE priority_product_search USING fts5(
                product_id UNINDEXED,
                search_text
            );",
        )?;
        Ok(())
    }

    fn insert_last_good_catalog(path: &Path) -> Result<(), rusqlite::Error> {
        let connection = Connection::open(path)?;
        connection.execute(
            "INSERT INTO priority_companies VALUES ('Last Good', 1, '', '', 1, '')",
            [],
        )?;
        connection.execute(
            "INSERT INTO priority_products (
                product_id, operation, contract_number, contract_sequence,
                category_number, category_name, detail_category_number, spec,
                company_name, unit, price_won, contract_method, delivery_condition,
                delivery_days, contract_end_date, image_url, detail_url, raw_json, observed_at
            ) VALUES (
                '87654321', 'getShoppingMallPrdctInfoList', 'old-contract', '1',
                '', 'last-good', '', '', 'Last Good', '', 1, '', '', '', '', '', '', '{}', 'old'
            )",
            [],
        )?;
        connection.execute(
            "INSERT INTO priority_product_offers (
                operation, offer_key, product_id, company_name, price_won, unit,
                contract_method, delivery_condition, delivery_days, contract_end_date,
                image_url, detail_url, raw_json, observed_at, active
            ) VALUES ('getShoppingMallPrdctInfoList', 'old-contract:1', '87654321',
                'Last Good', 1, '', '', '', '', '', '', '', '{}', 'old', 1)",
            [],
        )?;
        Ok(())
    }
}
