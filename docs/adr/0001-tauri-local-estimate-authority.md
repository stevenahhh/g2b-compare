# ADR 0001: Tauri local estimate authority

Status: Accepted

Date: 2026-08-04

## Context

The legacy browser client modeled estimate writes as local work waiting for a
remote authority. The Tauri desktop has a different boundary. It owns a local
SQLite database and must remain complete when no service is reachable.

## Decision

The AppData `g2b.sqlite3` database is the sole authority for Tauri estimates.
A successful native create, update, delete, or comparison refresh is final and
durable offline. Native CRUD never adds an item to `offline-replay.sqlite3`.

`offline-replay.sqlite3` is an import and recovery journal only. Replay checks
an imported change against the current saved revision, materializes it into
`g2b.sqlite3` once, then acknowledges it so retry can't apply it again. Failed
or conflicting items stay available for explicit recovery.

Saved and deleted events from another desktop writer still trigger
reconciliation. They cause a fresh read of the authoritative database and must
not overwrite an unsaved editor change.

## Consequences

Desktop UI and tests describe current saved changes and imported changes. They
don't model pending uploads or tombstones. Replay evidence proves exactly-once
local materialization in `g2b.sqlite3`.
