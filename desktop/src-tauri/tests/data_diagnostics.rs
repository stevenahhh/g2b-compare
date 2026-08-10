use std::{
    error::Error,
    fs,
    path::PathBuf,
    sync::{Arc, Mutex},
};

use g2b_compare_desktop_lib::data_diagnostics::{
    DataCounts, DataDiagnosticsState, DataStatus, DiagnosticError, OfficialDataRequest,
    OfficialDataTransport, ProviderResponse, SyncEventSink, SyncStage, SyncStatus, TransportError,
    official_sync_endpoint, sanitize_diagnostic,
};
use tempfile::tempdir;

#[test]
fn reports_the_seven_legacy_counts_and_readiness() {
    let counts = DataCounts {
        company_count: 3,
        product_count: 12,
        relation_count: 4,
        option_row_count: 7,
        unique_option_count: 5,
        pending_api_target_count: 2,
        pending_site_product_count: 1,
    };

    let status = DataStatus::from_counts(counts);

    assert_eq!(status.counts, counts);
    assert!(status.ready);
    assert_eq!(status.readiness, "ready");
}

#[test]
fn empty_catalog_is_not_ready_but_preserves_all_zero_counts() {
    let status = DataStatus::from_counts(DataCounts::default());

    assert!(!status.ready);
    assert_eq!(status.readiness, "empty");
    assert_eq!(status.counts.product_count, 0);
}

#[test]
fn refresh_failure_is_data_unavailable_and_does_not_replace_last_status() {
    let previous = DataStatus::from_counts(DataCounts {
        company_count: 3,
        product_count: 12,
        relation_count: 4,
        option_row_count: 7,
        unique_option_count: 5,
        pending_api_target_count: 2,
        pending_site_product_count: 1,
    });

    let failure = DiagnosticError::data_unavailable("database is temporarily locked");
    let retained = previous.retain_on_refresh_failure(&failure);

    assert_eq!(failure.public_code(), "data-unavailable");
    assert_eq!(retained, previous);
    assert_eq!(retained.error.as_deref(), Some("data-unavailable"));
}

#[test]
fn sync_status_is_serialized_as_the_legacy_stage_machine() {
    let running = SyncStatus::running(SyncStage::Sync);
    assert_eq!(running.state, "running");
    assert_eq!(running.stage, Some(SyncStage::Sync));

    let complete = SyncStatus::complete();
    assert_eq!(complete.state, "complete");
    assert_eq!(complete.stage, None);

    let failed = SyncStatus::failed(SyncStage::Materialize, "provider key leaked");
    assert_eq!(failed.state, "failed");
    assert_eq!(failed.stage, Some(SyncStage::Materialize));
    assert_eq!(failed.error.as_deref(), Some("provider key leaked"));
}

#[test]
fn sync_endpoint_is_fixed_to_the_official_host_and_path() {
    let endpoint = official_sync_endpoint();

    assert_eq!(endpoint.host(), "apis.data.go.kr");
    assert!(endpoint.path().starts_with('/'));
    assert!(!endpoint.path().contains("127.0.0.1"));
    assert!(!endpoint.path().contains("localhost"));
    assert!(endpoint.is_https());
}

#[test]
fn diagnostics_are_sanitized_without_credentials_or_provider_body() {
    let secret = "service-key-should-not-escape";
    let body = format!("HTTP 500 serviceKey={secret} raw provider payload");

    let sanitized = sanitize_diagnostic(500, &body, &[secret]);

    assert_eq!(sanitized, "HTTP 500");
    assert!(!sanitized.contains(secret));
    assert!(!sanitized.contains("raw provider payload"));
}

#[test]
fn status_reads_the_seven_counts_from_the_bootstrapped_production_seed()
-> Result<(), Box<dyn Error>> {
    let state = test_state(seed_database(), ProviderResponse::new(200));

    let status = state.status()?;

    assert_eq!(
        status.counts,
        DataCounts {
            company_count: 56,
            product_count: 27_854,
            relation_count: 19_852,
            option_row_count: 14_314,
            unique_option_count: 5_404,
            pending_api_target_count: 168,
            pending_site_product_count: 97,
        }
    );
    assert!(status.ready);
    assert_eq!(status.readiness, "ready");
    Ok(())
}

#[test]
fn unavailable_refresh_returns_last_known_good_counts() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("g2b.sqlite3");
    fs::copy(seed_database(), &database)?;
    let state = test_state(database.clone(), ProviderResponse::new(200));
    let previous = state.status()?;

    fs::write(&database, b"not a sqlite database")?;
    let retained = state.status()?;

    assert_eq!(retained, previous);
    assert_eq!(retained.error.as_deref(), Some("data-unavailable"));
    Ok(())
}

#[test]
fn sync_runs_the_python_stage_order_and_emits_each_transition() -> Result<(), Box<dyn Error>> {
    let runner = Arc::new(RecordingRunner::default());
    let events = RecordingEvents::default();
    let state = DataDiagnosticsState::with_components(
        seed_database(),
        Arc::new(StaticTransport::new(ProviderResponse::new(200))),
        runner.clone(),
    );

    let status = state.run_sync(&events);

    assert_eq!(status, SyncStatus::complete());
    assert_eq!(
        runner.stages()?,
        vec![
            SyncStage::Sync,
            SyncStage::ImportRelations,
            SyncStage::Materialize,
            SyncStage::RebuildIndex,
            SyncStage::Precompute,
        ]
    );
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
    Ok(())
}

#[test]
fn sync_failure_preserves_the_last_known_good_database() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("g2b.sqlite3");
    let original = b"last-known-good-database";
    fs::write(&database, original)?;
    let events = RecordingEvents::default();
    let state = DataDiagnosticsState::with_components(
        database.clone(),
        Arc::new(StaticTransport::new(ProviderResponse::new(200))),
        Arc::new(FailingRunner),
    );

    let status = state.run_sync(&events);

    assert_eq!(status, SyncStatus::failed(SyncStage::Sync, "HTTP 503"),);
    assert_eq!(fs::read(database)?, original);
    assert_eq!(events.statuses()?.last(), Some(&status));
    Ok(())
}

#[test]
fn diagnostics_use_the_fixed_endpoint_and_never_expose_provider_content()
-> Result<(), Box<dyn Error>> {
    let transport = Arc::new(StaticTransport::new(ProviderResponse::new(500)));
    let state = DataDiagnosticsState::with_components(
        seed_database(),
        transport.clone(),
        Arc::new(RecordingRunner::default()),
    );

    let result = state.diagnose();

    assert_eq!(result.state, "warning");
    assert!(!result.checked_at.is_empty());
    assert_eq!(result.code.as_deref(), Some("HTTP 500"));
    let requests = transport.requests()?;
    assert_eq!(requests.len(), 1);
    assert_eq!(requests[0].endpoint(), official_sync_endpoint());
    Ok(())
}

fn seed_database() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/seed.sqlite3")
}

fn test_state(database: PathBuf, response: ProviderResponse) -> DataDiagnosticsState {
    DataDiagnosticsState::with_components(
        database,
        Arc::new(StaticTransport::new(response)),
        Arc::new(RecordingRunner::default()),
    )
}

struct StaticTransport {
    response: ProviderResponse,
    requests: Mutex<Vec<OfficialDataRequest>>,
}

impl StaticTransport {
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

impl OfficialDataTransport for StaticTransport {
    fn execute(
        &self,
        request: OfficialDataRequest,
        _credential: g2b_compare_desktop_lib::remote::EmbeddedApiKey,
    ) -> Result<ProviderResponse, TransportError> {
        self.requests
            .lock()
            .map_err(|_| TransportError::Unavailable)?
            .push(request);
        Ok(self.response.clone())
    }
}

#[derive(Default)]
struct RecordingRunner {
    stages: Mutex<Vec<SyncStage>>,
}

impl RecordingRunner {
    fn stages(&self) -> Result<Vec<SyncStage>, Box<dyn Error>> {
        Ok(self
            .stages
            .lock()
            .map_err(|error| error.to_string())?
            .clone())
    }
}

impl g2b_compare_desktop_lib::data_diagnostics::DataSyncRunner for RecordingRunner {
    fn run_stage(&self, stage: SyncStage) -> Result<(), DiagnosticError> {
        self.stages
            .lock()
            .map_err(|_| DiagnosticError::data_unavailable("recording runner poisoned"))?
            .push(stage);
        Ok(())
    }
}

struct FailingRunner;

impl g2b_compare_desktop_lib::data_diagnostics::DataSyncRunner for FailingRunner {
    fn run_stage(&self, _stage: SyncStage) -> Result<(), DiagnosticError> {
        Err(DiagnosticError::ProviderStatus(503))
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
