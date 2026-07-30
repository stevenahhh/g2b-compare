# PYTHON PACKAGE KNOWLEDGE

## OVERVIEW

`g2b_compare` owns verified collection, local catalog/search, comparison,
estimates, and the FastAPI service. The dominant flow is:

```text
contracts -> sources -> sync -> db -> materialize
          -> normalize/search/ranking -> services -> web
```

The package-root `priority_*.py` and `company_*_crawl.py` modules form the
short-path priority catalog used by the current integrated MVP.

## WHERE TO LOOK

| Concern | Location |
|---|---|
| Endpoint/schema/quota truth | `contracts/` |
| HTTP envelope and transport adapters | `sources/` |
| Window, pagination, checkpoint, publish | `sync/` |
| Persistence and release identity | `db/` |
| Product/spec normalization | `materialize/`, `normalize/` |
| Recall and comparison formula | `search/`, `ranking/` |
| Search, release, estimate use cases | `services/` |
| CLI, health, runtime orchestration | `observability/` |
| HTTP, SPA, legacy pages | `web/` |
| External held-out quality gates | `evaluation/` |

## CONVENTIONS

- Support Python `>=3.12,<3.14`; basedpyright runs in `all` mode.
- Use Pydantic for untrusted boundaries and frozen/slotted dataclasses internally.
- Keep deterministic identifiers, sort order, Decimal behavior, and serialized formats stable.
- Use the typed SQLite helpers in `db.connection` and `db.sql` at repository seams.
- Raw provider bodies are content-addressed; snapshots and releases are append/publish flows.
- Primary search and comparison read local SQLite/index state. Network belongs to explicit
  capture, sync, crawl, or diagnostic-live paths.
- Translate provider/storage failures to stable secret-safe boundary errors.
- Logs carry only allowlisted operation context, never raw URLs, payloads, or credentials.

## ANTI-PATTERNS

- Do not activate incomplete source, materialization, index, relation, or cache state.
- Do not widen exact candidate membership through fuzzy/FTS recall.
- Do not infer approved option relations from simultaneous API appearance.
- Do not pass raw dictionaries or untyped SQLite rows across public boundaries.
- Do not add another runtime entry point when `cli.py`, `priority_cli.py`, or
  `scripts/start.py` already owns the operation.
- Do not treat historical handoff documents as newer than source/tests.

## TARGETED CHECKS

```powershell
uv run ruff check src/g2b_compare tests
uv run basedpyright
uv run pytest -q tests/<affected-domain>
uv run g2b-compare --help
```

For sync/release changes, prove a failed or partial run leaves the previous active
state unchanged. For CLI/web changes, exercise the real command or HTTP surface.
