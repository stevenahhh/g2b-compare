use std::{fs, io, path::PathBuf, time::Duration};

use rusqlite::{Connection, OptionalExtension, params};
use thiserror::Error;

use crate::db::{Migration, MigrationError, apply_migrations};

use super::EstimateViewState;

const VIEW_MIGRATIONS: [Migration; 1] = [Migration::new(
    "0001_initial",
    "
CREATE TABLE IF NOT EXISTS estimate_view_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    active_estimate_id TEXT
);
",
)];

#[derive(Debug, Error)]
pub enum EstimateViewStoreError {
    #[error("estimate view path has no parent directory")]
    MissingParent,
    #[error("active estimate ID must not be empty")]
    EmptyActiveEstimateId,
    #[error("estimate view I/O failed: {0}")]
    Io(#[from] io::Error),
    #[error(transparent)]
    Migration(#[from] MigrationError),
    #[error("estimate view database operation failed: {0}")]
    Sqlite(#[from] rusqlite::Error),
}

#[derive(Clone, Debug)]
pub struct EstimateViewStore {
    path: PathBuf,
}

impl EstimateViewStore {
    pub fn open(path: PathBuf) -> Result<Self, EstimateViewStoreError> {
        let parent = path.parent().ok_or(EstimateViewStoreError::MissingParent)?;
        fs::create_dir_all(parent)?;
        apply_migrations(&path, &VIEW_MIGRATIONS)?;
        Ok(Self { path })
    }

    pub fn load(&self) -> Result<Option<EstimateViewState>, EstimateViewStoreError> {
        self.connection()?
            .query_row(
                "SELECT active_estimate_id
                 FROM estimate_view_state WHERE singleton = 1",
                [],
                |row| {
                    Ok(EstimateViewState {
                        active_estimate_id: row.get(0)?,
                    })
                },
            )
            .optional()
            .map_err(EstimateViewStoreError::from)
    }

    pub fn save(&self, state: &EstimateViewState) -> Result<(), EstimateViewStoreError> {
        if state
            .active_estimate_id
            .as_deref()
            .is_some_and(|id| id.trim().is_empty())
        {
            return Err(EstimateViewStoreError::EmptyActiveEstimateId);
        }
        self.connection()?.execute(
            "INSERT INTO estimate_view_state (singleton, active_estimate_id)
             VALUES (1, ?1)
             ON CONFLICT(singleton) DO UPDATE SET
                 active_estimate_id = excluded.active_estimate_id",
            params![&state.active_estimate_id],
        )?;
        Ok(())
    }

    fn connection(&self) -> Result<Connection, rusqlite::Error> {
        let connection = Connection::open(&self.path)?;
        connection.busy_timeout(Duration::from_secs(5))?;
        Ok(connection)
    }
}
