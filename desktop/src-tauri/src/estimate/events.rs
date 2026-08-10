use serde::Serialize;
use tauri::{AppHandle, Emitter, EventTarget, Runtime, WebviewWindow};

/// The renderer event emitted after an estimate has been durably changed.
pub const ESTIMATE_CHANGE_EVENT: &str = "estimate-change";

/// The durable state transition for one estimate document.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EstimateChangeKind {
    Saved,
    Deleted,
}

/// The typed renderer-safe projection of a durable estimate transition.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct EstimateChangeEvent {
    pub id: String,
    pub kind: EstimateChangeKind,
    pub revision: Option<i64>,
}

impl EstimateChangeEvent {
    #[must_use]
    pub fn saved(id: impl Into<String>, revision: i64) -> Self {
        Self {
            id: id.into(),
            kind: EstimateChangeKind::Saved,
            revision: Some(revision),
        }
    }

    #[must_use]
    pub fn deleted(id: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            kind: EstimateChangeKind::Deleted,
            revision: None,
        }
    }
}

/// Broadcasts a durable estimate transition to every renderer.
///
/// Replay materialization has no renderer-local result to reconcile, so its event reaches the
/// initiating window too.
pub fn emit_estimate_change<R: Runtime>(
    app: &AppHandle<R>,
    change: EstimateChangeEvent,
) -> tauri::Result<()> {
    app.emit(ESTIMATE_CHANGE_EVENT, change)
}

/// Broadcasts a direct renderer mutation only to other windows.
///
/// The command response already updates the initiating renderer. Excluding it avoids a second
/// asynchronous read from racing that authoritative response while other desktop windows still
/// reconcile promptly.
pub fn emit_estimate_change_to_other_windows<R: Runtime>(
    app: &AppHandle<R>,
    source: &WebviewWindow<R>,
    change: EstimateChangeEvent,
) -> tauri::Result<()> {
    let source_label = source.label().to_owned();
    app.emit_filter(ESTIMATE_CHANGE_EVENT, change, |target| {
        !matches!(
            target,
            EventTarget::AnyLabel { label }
                | EventTarget::Window { label }
                | EventTarget::Webview { label }
                | EventTarget::WebviewWindow { label }
                if label == &source_label
        )
    })
}

#[cfg(test)]
mod tests {
    use super::{EstimateChangeEvent, EstimateChangeKind};

    #[test]
    fn events_distinguish_saved_revisions_from_deletions() {
        assert_eq!(
            EstimateChangeEvent::saved("estimate-a", 4),
            EstimateChangeEvent {
                id: "estimate-a".to_owned(),
                kind: EstimateChangeKind::Saved,
                revision: Some(4),
            }
        );
        assert_eq!(
            EstimateChangeEvent::deleted("estimate-a"),
            EstimateChangeEvent {
                id: "estimate-a".to_owned(),
                kind: EstimateChangeKind::Deleted,
                revision: None,
            }
        );
    }
}
