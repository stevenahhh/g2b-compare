# DATABASE AND RELEASE RULES

## OVERVIEW

This directory owns SQLite connection policy, ordered migrations, ingestion
provenance, immutable snapshots, raw retention, and active release consistency.

## WHERE TO LOOK

| Concern | File/area |
|---|---|
| Connection modes and pragmas | `connection.py` |
| Typed cursor/scalar facade | `sql.py` |
| Migration checksums | `migrate.py`, `migrations/` |
| Request/page ingestion | `ingest.py`, `models.py` |
| Source/catalog lifecycle | `repository.py`, `lifecycle.py` |
| Release validation/publish | `release*.py` |
| Content-addressed bodies | `raw.py`, `prune.py` |
| Shared test construction | `tests/db/support.py` |

## CONVENTIONS

- Migration files are ordered and checksum-locked after first application.
- Fix schema behavior with a new forward migration; never rewrite history.
- Normalize CRLF only where `migrate.py` already accounts for legacy checksums.
- Use explicit transactions for multi-step invariants and atomic publication.
- Parse SQLite cells through `as_int`, `as_text`, or another typed boundary.
- Snapshot rows are immutable after publish; a release pins an exact component set.
- Keep source body SHA, request fingerprint, page provenance, and catalog identity separate.
- Prune only unreferenced raw content; active provenance must remain resolvable.
- Tests use migrated `tmp_path` databases, not hand-copied development DBs.

## ANTI-PATTERNS

- No ad hoc schema mutation in repositories or tests.
- No manual entries in `schema_migrations`.
- No in-place mutation of published snapshots or active release components.
- No implicit mixing of rows from different catalog/materialization generations.
- No mutable filename as the identity of a raw provider body.
- No timing sleeps for lock/idempotency tests; coordinate on exact state/events.

## FOCUSED VERIFICATION

```powershell
uv run pytest -q tests/db
uv run pytest -q tests/materialize tests/sync
uv run ruff check src/g2b_compare/db tests/db
uv run basedpyright
```

Migration changes must be tested on both a fresh database and an already-migrated
fixture when compatibility is part of the contract.
