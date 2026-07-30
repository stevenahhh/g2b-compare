# PROJECT KNOWLEDGE BASE

**Generated:** 2026-07-29
**Commit:** `332a0e0`
**Branch:** `main`

## OVERVIEW

Windows-first local procurement workspace with three code products:
the Python G2B service, a Svelte SPA embedded into that service, and an
independent Electron workbook estimator. Data provenance, deterministic
ranking, offline-safe edits, and fail-closed export/security checks are core.

## STRUCTURE

```text
./
├── src/g2b_compare/       # Python collection, search, service, and FastAPI code
├── frontend/              # Svelte source; builds into the Python package
├── electron-estimator/    # Separate strict TypeScript/Electron application
├── tests/                 # Python tests mirroring backend domains
├── docs/                  # Architecture, contracts, runbooks, limitations
├── scripts/               # Windows launch, sync, crawl, portable-package flows
├── tools/                 # Evaluation and workbook developer utilities
└── typings/               # Local scientific-library typing supplements
```

Generated, runtime, cache, evidence, and staging trees are not source:
`.g2b/`, `.omo/`, `.codegraph/`, `dist/`, `release/`, `tmp/`, `outputs/`,
`node_modules/`, caches, and test reports.

## WHERE TO LOOK

| Task | Location | Notes |
|---|---|---|
| Start local service | `scripts/start.py` | `--home .g2b` selects `.g2b/g2b.sqlite3`; initializes, scans secrets, serves port 8765 |
| CLI operation | `src/g2b_compare/cli.py` | Parses then delegates to observability actions |
| G2B contract/source sync | `src/g2b_compare/contracts/`, `sources/`, `sync/` | Network and checkpoint boundary |
| SQLite/release lifecycle | `src/g2b_compare/db/` | Migrations, provenance, immutable releases |
| Search/comparison | `normalize/`, `search/`, `ranking/`, `services/` | Local deterministic execution |
| HTTP/API behavior | `src/g2b_compare/web/` | SPA, legacy routes, health/readiness |
| Browser UI | `frontend/src/` | Routes, IndexedDB, pending synchronization |
| Electron privilege boundary | `electron-estimator/src/main/`, `preload/` | Protocol, IPC, capabilities |
| Workbook generation | `electron-estimator/src/native/`, `legacy/` | Native and compatibility workflows |
| Python acceptance contracts | `tests/acceptance/` | Scenario registries and provenance receipts |

## CODE MAP

| Symbol | Type | Location | Refs | Role |
|---|---|---|---:|---|
| `main` | function | `src/g2b_compare/cli.py:17` | entry | Installed CLI boundary |
| `dispatch` | function | `src/g2b_compare/observability/cli_actions.py:39` | 3 | Operation router |
| `migrate` | function | `src/g2b_compare/db/migrate.py:39` | 74 | Checksum-locked schema setup |
| `run_catalog_sync` | function | `src/g2b_compare/observability/runtime_sync.py:141` | 14 | Live sync orchestration |
| `execute_search` | function | `src/g2b_compare/services/search.py:70` | 44 | Local search use case |
| `create_app` | function | `src/g2b_compare/web/app.py:106` | 60 | FastAPI composition root |
| `App` | component | `frontend/src/App.svelte:1` | dynamic | SPA state and route owner |
| `syncPendingEstimates` | function | `frontend/src/lib/sync.js:9` | 11 | Serialized offline mutation sync |
| `executeIpcBoundary` | function | `electron-estimator/src/main/ipc-boundary.ts:55` | 5 | Validated IPC execution |
| `registerAppProtocol` | function | `electron-estimator/src/main/protocol.ts:114` | 2 | Hardened local asset protocol |
| `exportLegacyWorkbook` | function | `electron-estimator/src/legacy/export/index.ts:60` | central | Atomic workbook publication |

## CONVENTIONS

- Python: 3.12/3.13, `uv`, Hatch `src/` layout, basedpyright `all`, Ruff `ALL`.
- Python models are typed and frozen by default; validate untrusted I/O at boundaries.
- Source snapshots, materializations, indexes, and release pointers have distinct identities.
- Svelte is a package boundary; its production output is tracked under
  `src/g2b_compare/web/frontend_dist/` but must be regenerated, never hand-edited.
- Electron is not a wrapper around the Python app; run its package-local gates.
- `DESIGN.md` governs the web UI; `electron-estimator/DESIGN.md` governs Electron.
- Prefer current source and tests over historical `.omo` plans or implementation handoffs.

## ANTI-PATTERNS

- No secrets, raw API payloads, runtime databases, or credentials in source/logs/manifests.
- No network calls in primary local search/ranking paths; live diagnostic routes are explicit.
- Never publish partial sync/build state over the last known-good release.
- Never infer parent/option relations from API co-occurrence or scrape G2B pages for them.
- Never edit applied SQL migrations, generated SPA bundles, `dist/`, ASAR contents, or evidence.
- Never bypass Electron sender/capability validation or expose Node/raw IPC to the renderer.
- Never overwrite a source workbook or evaluate imported formula text.

## COMMANDS

```powershell
# Service
uv run python .\scripts\start.py --home .g2b

# Headless service using the same populated database
uv run g2b-compare --home .g2b serve --host 127.0.0.1 --port 8765

# Python gates
uv run ruff format --check .
uv run ruff check .
uv run basedpyright
uv run pytest -q

# Svelte package
cd frontend
npm ci
npm test -- --run
npm run build

# Electron package
cd electron-estimator
npm ci
npm run verify:all
```

## NOTES

- `scripts/start.py` and its acceptance test bind the server to `0.0.0.0`, probe/open
  via `127.0.0.1`, and print a LAN URL. `README.md` still says loopback-only.
- `--home .g2b` resolves the service database to `.g2b/g2b.sqlite3`. Do not use
  `uv run uvicorn g2b_compare.web.app:app` for populated-data QA; the module-level
  fallback resolves `data/g2b-compare.sqlite3`, which may be an empty development DB.
- No tracked CI workflow exists; repository and package verification commands are the gates.
- A fresh SPA build is required by `tests/web/test_spa_delivery.py`.
- Full Electron verification also packages ASAR, runs runtime smoke tests, an artifact
  oracle, and cleanup audit; a green unit suite alone is insufficient.
