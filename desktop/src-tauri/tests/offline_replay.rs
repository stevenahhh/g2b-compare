use std::{
    error::Error,
    sync::{Arc, Barrier, Mutex},
};

use g2b_compare_desktop_lib::offline_replay::{
    Mutation, ReconciliationEvent, ReplayDecision, ReplayError, ReplayStore, ReplayTarget,
};
use tempfile::tempdir;

#[derive(Default)]
struct RecordingTarget {
    applied: Vec<u64>,
    conflicts: Vec<u64>,
}

impl ReplayTarget for RecordingTarget {
    fn apply(&mut self, mutation: &Mutation) -> Result<ReplayDecision, ReplayError> {
        self.applied.push(mutation.sequence);
        if self.conflicts.contains(&mutation.sequence) {
            Ok(ReplayDecision::Conflict {
                reason: "remote revision differs".to_owned(),
            })
        } else {
            Ok(ReplayDecision::Applied)
        }
    }
}

fn mutation(entity_id: &str, payload: &[u8]) -> Mutation {
    Mutation::new(entity_id.to_owned(), payload.to_vec())
}

#[test]
fn queued_mutations_are_durable_and_receive_monotonic_sequences() -> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("offline-replay.sqlite3");

    let first = ReplayStore::open(&path)?;
    let first_sequence = first.enqueue(mutation("estimate-a", br#"{"title":"first"}"#))?;
    let second_sequence = first.enqueue(mutation("estimate-b", br#"{"title":"second"}"#))?;
    drop(first);

    let reopened = ReplayStore::open(&path)?;
    let queued = reopened.pending()?;

    assert_eq!((first_sequence, second_sequence), (1, 2));
    assert_eq!(
        queued.iter().map(|item| item.sequence).collect::<Vec<_>>(),
        [1, 2]
    );
    assert_eq!(queued[0].entity_id, "estimate-a");
    assert_eq!(queued[1].entity_id, "estimate-b");
    Ok(())
}

#[test]
fn replay_is_ordered_exactly_once_and_emits_reconciliation_events() -> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("offline-replay.sqlite3");
    let store = ReplayStore::open(&path)?;
    store.enqueue(mutation("estimate-a", br#"{"title":"first"}"#))?;
    store.enqueue(mutation("estimate-b", br#"{"title":"second"}"#))?;

    let mut events = Vec::new();
    let mut target = RecordingTarget::default();
    store.replay(&mut target, |event| events.push(event))?;

    assert_eq!(target.applied, [1, 2]);
    assert!(matches!(
        events.first(),
        Some(ReconciliationEvent::Applied { sequence: 1, .. })
    ));
    assert!(matches!(
        events.get(1),
        Some(ReconciliationEvent::Applied { sequence: 2, .. })
    ));
    assert!(store.pending()?.is_empty());

    let mut retry_target = RecordingTarget::default();
    store.replay(&mut retry_target, |_| {})?;
    assert!(
        retry_target.applied.is_empty(),
        "a completed mutation must not be replayed twice"
    );
    Ok(())
}

#[test]
fn conflicts_are_retained_and_reported_without_losing_later_ordered_work()
-> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("offline-replay.sqlite3");
    let store = ReplayStore::open(&path)?;
    store.enqueue(mutation("estimate-a", br#"{"title":"conflict"}"#))?;
    store.enqueue(mutation("estimate-b", br#"{"title":"apply"}"#))?;

    let mut events = Vec::new();
    let mut target = RecordingTarget {
        conflicts: vec![1],
        ..RecordingTarget::default()
    };
    store.replay(&mut target, |event| events.push(event))?;

    assert_eq!(target.applied, [1, 2]);
    assert!(matches!(
        events.first(),
        Some(ReconciliationEvent::Conflict { sequence: 1, .. })
    ));
    assert!(matches!(
        events.get(1),
        Some(ReconciliationEvent::Applied { sequence: 2, .. })
    ));
    assert_eq!(
        store
            .pending()?
            .iter()
            .map(|item| item.sequence)
            .collect::<Vec<_>>(),
        [1]
    );
    Ok(())
}

#[test]
fn restart_recovers_failed_work_and_replays_it_after_an_explicit_retry_barrier()
-> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("offline-replay.sqlite3");
    let store = ReplayStore::open(&path)?;
    store.enqueue(mutation("estimate-a", br#"{"title":"retry"}"#))?;

    let mut failed_target = FailingTarget;
    assert!(store.replay(&mut failed_target, |_| {}).is_err());
    drop(store);

    let reopened = ReplayStore::open(&path)?;
    let mut target = RecordingTarget::default();
    let release = Arc::new(Barrier::new(2));
    let events = Arc::new(Mutex::new(Vec::new()));
    let replay_release = Arc::clone(&release);
    let replay_events = Arc::clone(&events);
    let replay_thread = std::thread::spawn(move || {
        reopened.replay(&mut target, |event| {
            replay_release.wait();
            if let Ok(mut recorded) = replay_events.lock() {
                recorded.push(event);
            }
        })
    });
    release.wait();
    match replay_thread.join() {
        Ok(result) => result?,
        Err(_) => return Err("offline replay worker panicked".into()),
    }
    let recorded = events
        .lock()
        .map_err(|_| "offline replay event lock was poisoned")?;
    assert!(matches!(
        recorded.first(),
        Some(ReconciliationEvent::Applied { sequence: 1, .. })
    ));
    drop(recorded);
    Ok(())
}

struct FailingTarget;

impl ReplayTarget for FailingTarget {
    fn apply(&mut self, _mutation: &Mutation) -> Result<ReplayDecision, ReplayError> {
        Err(ReplayError::Transport("offline".to_owned()))
    }
}

#[test]
fn malformed_persisted_payload_fails_closed_without_emitting_or_applying()
-> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("offline-replay.sqlite3");
    let store = ReplayStore::open(&path)?;
    store.enqueue(mutation("estimate-a", b"not-json"))?;

    let mut target = RecordingTarget::default();
    let mut events = Vec::new();
    let result = store.replay(&mut target, |event| events.push(event));

    assert!(matches!(result, Err(ReplayError::MalformedPayload { .. })));
    assert!(target.applied.is_empty());
    assert!(events.is_empty());
    assert_eq!(
        store
            .pending()?
            .iter()
            .map(|item| item.sequence)
            .collect::<Vec<_>>(),
        [1]
    );
    Ok(())
}
