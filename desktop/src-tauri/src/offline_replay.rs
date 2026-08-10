use std::{
    path::Path,
    sync::{Mutex, MutexGuard},
};

use rusqlite::{Connection, TransactionBehavior, params};
use thiserror::Error;

use crate::db::{Migration, MigrationError, apply_migrations};

const MAX_JSON_NESTING: usize = 128;
const REPLAY_MIGRATIONS: [Migration; 1] = [Migration::new(
    "0001_initial",
    "
CREATE TABLE IF NOT EXISTS offline_replay_mutations (
     sequence INTEGER PRIMARY KEY AUTOINCREMENT CHECK (sequence > 0),
     entity_id TEXT NOT NULL,
     payload BLOB NOT NULL
 ) STRICT;
 CREATE TABLE IF NOT EXISTS offline_replay_conflicts (
     sequence INTEGER PRIMARY KEY REFERENCES offline_replay_mutations(sequence) ON DELETE CASCADE,
     entity_id TEXT NOT NULL,
     reason_code TEXT NOT NULL
 ) STRICT;
",
)];

/// A mutation waiting to be reconciled with its remote target.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Mutation {
    /// The durable, monotonically increasing queue position.
    pub sequence: u64,
    /// The local entity affected by this mutation.
    pub entity_id: String,
    /// The JSON document that must be applied to the entity.
    pub payload: Vec<u8>,
}

impl Mutation {
    /// Creates a mutation before it has been assigned its durable sequence.
    #[must_use]
    pub const fn new(entity_id: String, payload: Vec<u8>) -> Self {
        Self {
            sequence: 0,
            entity_id,
            payload,
        }
    }
}

/// The outcome reported by a replay target for one mutation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ReplayDecision {
    /// The target accepted the mutation and it can be removed from the queue.
    Applied,
    /// The target detected a conflict, so the mutation remains queued.
    Conflict {
        /// A user-facing explanation supplied by the target.
        reason: String,
    },
}

/// A synchronous update emitted after one replay decision is durably handled.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ReconciliationEvent {
    /// An applied mutation was committed as removed from the durable queue.
    Applied {
        /// The durable queue sequence of the mutation.
        sequence: u64,
        /// The entity affected by the mutation.
        entity_id: String,
    },
    /// A conflicting mutation was retained in the durable queue.
    Conflict {
        /// The durable queue sequence of the mutation.
        sequence: u64,
        /// The entity affected by the mutation.
        entity_id: String,
        /// The renderer-safe conflict explanation supplied by the target.
        reason: String,
    },
}

/// A durable unresolved conflict attached to one queued mutation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReplayConflict {
    /// The durable queue sequence of the mutation requiring resolution.
    pub sequence: u64,
    /// The entity affected by the queued mutation.
    pub entity_id: String,
    /// A stable renderer-safe reason code.
    pub reason_code: String,
}

/// The user's resolution for one durable conflict.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ConflictResolution {
    /// Retain the queued local mutation and make it eligible for a future replay.
    KeepLocal,
    /// Discard the queued local mutation in favor of the remote record.
    UseRemote,
}

/// Failures while storing or replaying local mutations.
#[derive(Debug, Error)]
pub enum ReplayError {
    /// The durable `SQLite` queue could not be read or written.
    #[error("offline replay database operation failed: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error(transparent)]
    Migration(#[from] MigrationError),
    /// A target transport failure prevented replaying the current mutation.
    #[error("offline replay transport failed: {0}")]
    Transport(String),
    /// `SQLite` could not enter write-ahead-log mode for the durable queue.
    #[error("offline replay database did not enter WAL mode: {mode}")]
    JournalMode {
        /// The journal mode returned by `SQLite`.
        mode: String,
    },
    /// A persisted payload is not a complete JSON document.
    #[error("offline replay mutation {sequence} has a malformed JSON payload: {reason}")]
    MalformedPayload {
        /// The durable queue sequence of the malformed mutation.
        sequence: u64,
        /// The validation failure that prevented target invocation.
        reason: String,
    },
    /// A persisted sequence is outside the queue's supported positive range.
    #[error("offline replay database contains an invalid sequence: {sequence}")]
    InvalidStoredSequence {
        /// The raw `SQLite` sequence value.
        sequence: i64,
    },
    /// A requested sequence cannot be represented by `SQLite`'s signed integer type.
    #[error("offline replay sequence is outside SQLite's supported range: {sequence}")]
    SequenceOutOfRange {
        /// The sequence supplied by the caller.
        sequence: u64,
    },
    /// A mutation disappeared after the target reported it applied.
    #[error("offline replay mutation {sequence} disappeared before durable acknowledgement")]
    MissingAppliedMutation {
        /// The mutation sequence that could not be deleted.
        sequence: u64,
    },
    /// A replay operation cannot continue after an earlier caller panicked while holding its lock.
    #[error("offline replay state lock is poisoned")]
    StatePoisoned,
    /// The requested mutation does not have a durable unresolved conflict.
    #[error("offline replay conflict {sequence} was not found")]
    ConflictNotFound {
        /// The requested durable queue sequence.
        sequence: u64,
    },
}

/// Applies a queued mutation to a remote system.
pub trait ReplayTarget {
    /// Applies one valid JSON mutation.
    ///
    /// # Errors
    ///
    /// Returns an error when the target cannot determine a durable decision. The
    /// mutation remains queued and later mutations are not attempted.
    fn apply(&mut self, mutation: &Mutation) -> Result<ReplayDecision, ReplayError>;
}

/// A SQLite-backed queue that serializes local mutation replay.
pub struct ReplayStore {
    connection: Mutex<Connection>,
    replay_lock: Mutex<()>,
}

impl ReplayStore {
    /// Opens a durable replay queue, creating its schema when necessary.
    ///
    /// # Errors
    ///
    /// Returns an error when `SQLite` cannot open, configure, or initialize the queue.
    pub fn open(path: impl AsRef<Path>) -> Result<Self, ReplayError> {
        apply_migrations(path.as_ref(), &REPLAY_MIGRATIONS)?;
        let connection = Connection::open(path)?;
        configure_connection(&connection)?;
        Ok(Self {
            connection: Mutex::new(connection),
            replay_lock: Mutex::new(()),
        })
    }

    /// Persists a mutation and returns its monotonic durable sequence.
    ///
    /// # Errors
    ///
    /// Returns an error without assigning a sequence when `SQLite` cannot commit the insertion.
    pub fn enqueue(&self, mutation: Mutation) -> Result<u64, ReplayError> {
        let Mutation {
            entity_id, payload, ..
        } = mutation;
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        transaction.execute(
            "INSERT INTO offline_replay_mutations (entity_id, payload) VALUES (?1, ?2)",
            params![entity_id, payload],
        )?;
        let sequence = sequence_from_sql(transaction.last_insert_rowid())?;
        transaction.commit()?;
        drop(connection);
        Ok(sequence)
    }

    /// Returns every queued mutation in durable sequence order, including unresolved conflicts.
    ///
    /// # Errors
    ///
    /// Returns an error when `SQLite` cannot read the queue or the persisted data is invalid.
    pub fn pending(&self) -> Result<Vec<Mutation>, ReplayError> {
        let connection = self.connection()?;
        pending_from_connection(&connection)
    }

    /// Returns every durable unresolved conflict in queue sequence order.
    ///
    /// # Errors
    ///
    /// Returns an error when the replay queue cannot be read or contains an invalid sequence.
    pub fn conflicts(&self) -> Result<Vec<ReplayConflict>, ReplayError> {
        let connection = self.connection()?;
        conflicts_from_connection(&connection)
    }

    /// Resolves one durable conflict transactionally.
    ///
    /// `KeepLocal` keeps the mutation and removes only its conflict marker, making it eligible for
    /// a new replay. `UseRemote` removes the mutation and its conflict marker together.
    ///
    /// # Errors
    ///
    /// Returns `ConflictNotFound` when the requested unresolved conflict does not exist.
    pub fn resolve_conflict(
        &self,
        sequence: u64,
        resolution: ConflictResolution,
    ) -> Result<(), ReplayError> {
        let _replay_guard = self.replay_lock()?;
        let sql_sequence = sequence_to_sql(sequence)?;
        let mut connection = self.connection()?;
        {
            let transaction =
                connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
            let conflict_exists = transaction.query_row(
                "SELECT 1 FROM offline_replay_conflicts WHERE sequence = ?1",
                [sql_sequence],
                |_| Ok(()),
            );
            match conflict_exists {
                Ok(()) => {}
                Err(rusqlite::Error::QueryReturnedNoRows) => {
                    return Err(ReplayError::ConflictNotFound { sequence });
                }
                Err(error) => return Err(ReplayError::Sqlite(error)),
            }
            match resolution {
                ConflictResolution::KeepLocal => {
                    transaction.execute(
                        "DELETE FROM offline_replay_conflicts WHERE sequence = ?1",
                        [sql_sequence],
                    )?;
                }
                ConflictResolution::UseRemote => {
                    let deleted = transaction.execute(
                        "DELETE FROM offline_replay_mutations WHERE sequence = ?1",
                        [sql_sequence],
                    )?;
                    if deleted != 1 {
                        return Err(ReplayError::MissingAppliedMutation { sequence });
                    }
                }
            }
            transaction.commit()?;
        }
        drop(connection);
        Ok(())
    }

    /// Replays currently queued mutations in sequence order and emits each decision synchronously.
    ///
    /// Applied mutations are transactionally deleted before their events are emitted. Conflicts
    /// remain in the queue, while later queued mutations continue to be considered. A target error
    /// stops replay at that mutation so the failed and later work remain available after restart.
    ///
    /// # Errors
    ///
    /// Returns an error when a payload is malformed, the target fails, or `SQLite` cannot durably
    /// acknowledge an applied mutation. No event is emitted for the mutation that caused the error.
    pub fn replay<Target, Emit>(
        &self,
        target: &mut Target,
        mut emit: Emit,
    ) -> Result<(), ReplayError>
    where
        Target: ReplayTarget + ?Sized,
        Emit: FnMut(ReconciliationEvent),
    {
        let _replay_guard = self.replay_lock()?;
        let queued = self.replayable()?;

        for mutation in queued {
            validate_json(&mutation.payload).map_err(|reason| ReplayError::MalformedPayload {
                sequence: mutation.sequence,
                reason: reason.to_owned(),
            })?;

            match target.apply(&mutation)? {
                ReplayDecision::Applied => {
                    self.delete_applied(mutation.sequence)?;
                    emit(ReconciliationEvent::Applied {
                        sequence: mutation.sequence,
                        entity_id: mutation.entity_id,
                    });
                }
                ReplayDecision::Conflict { reason } => {
                    let reason_code = normalize_reason_code(&reason);
                    self.record_conflict(&mutation, &reason_code)?;
                    emit(ReconciliationEvent::Conflict {
                        sequence: mutation.sequence,
                        entity_id: mutation.entity_id,
                        reason: reason_code,
                    });
                }
            }
        }

        Ok(())
    }

    fn connection(&self) -> Result<MutexGuard<'_, Connection>, ReplayError> {
        self.connection
            .lock()
            .map_err(|_| ReplayError::StatePoisoned)
    }

    fn replay_lock(&self) -> Result<MutexGuard<'_, ()>, ReplayError> {
        self.replay_lock
            .lock()
            .map_err(|_| ReplayError::StatePoisoned)
    }

    fn replayable(&self) -> Result<Vec<Mutation>, ReplayError> {
        let connection = self.connection()?;
        replayable_from_connection(&connection)
    }

    fn delete_applied(&self, sequence: u64) -> Result<(), ReplayError> {
        let sql_sequence = sequence_to_sql(sequence)?;
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let deleted = transaction.execute(
            "DELETE FROM offline_replay_mutations WHERE sequence = ?1",
            [sql_sequence],
        )?;
        if deleted != 1 {
            return Err(ReplayError::MissingAppliedMutation { sequence });
        }
        transaction.commit()?;
        drop(connection);
        Ok(())
    }

    fn record_conflict(&self, mutation: &Mutation, reason_code: &str) -> Result<(), ReplayError> {
        let sql_sequence = sequence_to_sql(mutation.sequence)?;
        let mut connection = self.connection()?;
        {
            let transaction =
                connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
            transaction.execute(
                "INSERT INTO offline_replay_conflicts (sequence, entity_id, reason_code)
                 VALUES (?1, ?2, ?3)
                 ON CONFLICT(sequence) DO UPDATE SET
                     entity_id = excluded.entity_id,
                     reason_code = excluded.reason_code",
                params![sql_sequence, &mutation.entity_id, reason_code],
            )?;
            transaction.commit()?;
        }
        drop(connection);
        Ok(())
    }
}

fn configure_connection(connection: &Connection) -> Result<(), ReplayError> {
    connection.pragma_update(None, "foreign_keys", true)?;
    let journal_mode = connection.query_row("PRAGMA journal_mode = WAL", [], |row| {
        row.get::<_, String>(0)
    })?;
    if !journal_mode.eq_ignore_ascii_case("wal") {
        return Err(ReplayError::JournalMode { mode: journal_mode });
    }
    connection.pragma_update(None, "synchronous", "FULL")?;
    Ok(())
}

fn pending_from_connection(connection: &Connection) -> Result<Vec<Mutation>, ReplayError> {
    let mut statement = connection.prepare(
        "SELECT sequence, entity_id, payload
         FROM offline_replay_mutations
         ORDER BY sequence ASC",
    )?;
    let rows = statement.query_map([], |row| {
        Ok((
            row.get::<_, i64>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, Vec<u8>>(2)?,
        ))
    })?;
    rows.map(|row| {
        let (sequence, entity_id, payload) = row?;
        Ok(Mutation {
            sequence: sequence_from_sql(sequence)?,
            entity_id,
            payload,
        })
    })
    .collect()
}

fn replayable_from_connection(connection: &Connection) -> Result<Vec<Mutation>, ReplayError> {
    let mut statement = connection.prepare(
        "SELECT mutation.sequence, mutation.entity_id, mutation.payload
         FROM offline_replay_mutations AS mutation
         WHERE NOT EXISTS (
             SELECT 1 FROM offline_replay_conflicts AS conflict
             WHERE conflict.sequence = mutation.sequence
         )
         ORDER BY mutation.sequence ASC",
    )?;
    let rows = statement.query_map([], |row| {
        Ok((
            row.get::<_, i64>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, Vec<u8>>(2)?,
        ))
    })?;
    rows.map(|row| {
        let (sequence, entity_id, payload) = row?;
        Ok(Mutation {
            sequence: sequence_from_sql(sequence)?,
            entity_id,
            payload,
        })
    })
    .collect()
}

fn conflicts_from_connection(connection: &Connection) -> Result<Vec<ReplayConflict>, ReplayError> {
    let mut statement = connection.prepare(
        "SELECT sequence, entity_id, reason_code
         FROM offline_replay_conflicts
         ORDER BY sequence ASC",
    )?;
    let rows = statement.query_map([], |row| {
        Ok((
            row.get::<_, i64>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
        ))
    })?;
    rows.map(|row| {
        let (sequence, entity_id, reason_code) = row?;
        Ok(ReplayConflict {
            sequence: sequence_from_sql(sequence)?,
            entity_id,
            reason_code,
        })
    })
    .collect()
}

fn normalize_reason_code(value: &str) -> String {
    let valid = !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-');
    if valid {
        value.to_owned()
    } else {
        "replay-conflict".to_owned()
    }
}

fn sequence_from_sql(sequence: i64) -> Result<u64, ReplayError> {
    if sequence <= 0 {
        return Err(ReplayError::InvalidStoredSequence { sequence });
    }
    u64::try_from(sequence).map_err(|_| ReplayError::InvalidStoredSequence { sequence })
}

fn sequence_to_sql(sequence: u64) -> Result<i64, ReplayError> {
    i64::try_from(sequence).map_err(|_| ReplayError::SequenceOutOfRange { sequence })
}

fn validate_json(payload: &[u8]) -> Result<(), &'static str> {
    if std::str::from_utf8(payload).is_err() {
        return Err("payload is not valid UTF-8");
    }
    JsonParser::new(payload).parse_document()
}

struct JsonParser<'payload> {
    payload: &'payload [u8],
    position: usize,
}

impl<'payload> JsonParser<'payload> {
    const fn new(payload: &'payload [u8]) -> Self {
        Self {
            payload,
            position: 0,
        }
    }

    fn parse_document(&mut self) -> Result<(), &'static str> {
        self.skip_whitespace();
        self.parse_value(0)?;
        self.skip_whitespace();
        if self.position == self.payload.len() {
            Ok(())
        } else {
            Err("payload contains trailing content")
        }
    }

    fn parse_value(&mut self, depth: usize) -> Result<(), &'static str> {
        match self.peek() {
            Some(b'{') => self.parse_object(depth),
            Some(b'[') => self.parse_array(depth),
            Some(b'\"') => self.parse_string(),
            Some(b'-' | b'0'..=b'9') => self.parse_number(),
            Some(b't') => self.parse_literal(b"true"),
            Some(b'f') => self.parse_literal(b"false"),
            Some(b'n') => self.parse_literal(b"null"),
            _ => Err("payload does not begin with a JSON value"),
        }
    }

    fn parse_object(&mut self, depth: usize) -> Result<(), &'static str> {
        self.require(b'{', "expected an object")?;
        let depth = next_depth(depth)?;
        self.skip_whitespace();
        if self.consume(b'}') {
            return Ok(());
        }

        loop {
            self.parse_string()?;
            self.skip_whitespace();
            self.require(b':', "object member is missing a colon")?;
            self.skip_whitespace();
            self.parse_value(depth)?;
            self.skip_whitespace();
            if self.consume(b'}') {
                return Ok(());
            }
            self.require(b',', "object members are not comma-separated")?;
            self.skip_whitespace();
        }
    }

    fn parse_array(&mut self, depth: usize) -> Result<(), &'static str> {
        self.require(b'[', "expected an array")?;
        let depth = next_depth(depth)?;
        self.skip_whitespace();
        if self.consume(b']') {
            return Ok(());
        }

        loop {
            self.parse_value(depth)?;
            self.skip_whitespace();
            if self.consume(b']') {
                return Ok(());
            }
            self.require(b',', "array values are not comma-separated")?;
            self.skip_whitespace();
        }
    }

    fn parse_string(&mut self) -> Result<(), &'static str> {
        self.require(b'\"', "expected a JSON string")?;
        loop {
            match self.take() {
                Some(b'\"') => return Ok(()),
                Some(b'\\') => self.parse_escape()?,
                Some(0..=0x1f) => {
                    return Err("JSON string contains an unescaped control character");
                }
                Some(_) => {}
                None => return Err("JSON string is not terminated"),
            }
        }
    }

    fn parse_escape(&mut self) -> Result<(), &'static str> {
        match self.take() {
            Some(b'\"' | b'\\' | b'/' | b'b' | b'f' | b'n' | b'r' | b't') => Ok(()),
            Some(b'u') => self.parse_unicode_escape(),
            _ => Err("JSON string contains an invalid escape sequence"),
        }
    }

    fn parse_unicode_escape(&mut self) -> Result<(), &'static str> {
        for _ in 0..4 {
            let byte = self.take().ok_or("JSON Unicode escape is incomplete")?;
            if !byte.is_ascii_hexdigit() {
                return Err("JSON Unicode escape contains a non-hex digit");
            }
        }
        Ok(())
    }

    fn parse_number(&mut self) -> Result<(), &'static str> {
        self.consume(b'-');
        match self.peek() {
            Some(b'0') => self.position += 1,
            Some(b'1'..=b'9') => {
                self.consume_digits();
            }
            _ => return Err("JSON number has no integer component"),
        }

        if self.consume(b'.') && !self.consume_digits() {
            return Err("JSON number has no fractional component");
        }
        if matches!(self.peek(), Some(b'e' | b'E')) {
            self.position += 1;
            if matches!(self.peek(), Some(b'+' | b'-')) {
                self.position += 1;
            }
            if !self.consume_digits() {
                return Err("JSON number has no exponent component");
            }
        }
        Ok(())
    }

    fn parse_literal(&mut self, literal: &[u8]) -> Result<(), &'static str> {
        if self.payload[self.position..].starts_with(literal) {
            self.position += literal.len();
            Ok(())
        } else {
            Err("payload contains an invalid JSON literal")
        }
    }

    fn consume_digits(&mut self) -> bool {
        let start = self.position;
        while matches!(self.peek(), Some(byte) if byte.is_ascii_digit()) {
            self.position += 1;
        }
        self.position > start
    }

    fn skip_whitespace(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\n' | b'\r' | b'\t')) {
            self.position += 1;
        }
    }

    fn require(&mut self, expected: u8, error: &'static str) -> Result<(), &'static str> {
        if self.consume(expected) {
            Ok(())
        } else {
            Err(error)
        }
    }

    fn consume(&mut self, expected: u8) -> bool {
        if self.peek() == Some(expected) {
            self.position += 1;
            true
        } else {
            false
        }
    }

    fn peek(&self) -> Option<u8> {
        self.payload.get(self.position).copied()
    }

    fn take(&mut self) -> Option<u8> {
        let byte = self.peek()?;
        self.position += 1;
        Some(byte)
    }
}

const fn next_depth(depth: usize) -> Result<usize, &'static str> {
    match depth.checked_add(1) {
        Some(next) if next <= MAX_JSON_NESTING => Ok(next),
        _ => Err("JSON nesting exceeds the supported limit"),
    }
}
