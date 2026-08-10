# Tauri Desktop Parity Matrix

This matrix is the binding acceptance inventory for the isolated desktop
rewrite. A row is complete only when its named RED test, GREEN implementation,
packaged GUI action, and evidence receipt exist.

Machine-consumed columns are `ID`, `Legacy evidence`, `Desktop seam`, `RED
proof`, and `Surface proof`. IDs are immutable and unique.

## Shell, navigation, and global state

| ID | Observable contract | Legacy evidence | Desktop seam | RED proof | Surface proof |
|---|---|---|---|---|---|
| SHELL-001 | Root opens the catalog view | `frontend/src/router.js:1-26` | `src/App.svelte`, `src/lib/stores/shell.ts` | `shell.routes.test.ts: root→catalog` | `full-parity: open root; catalog heading visible` |
| SHELL-002 | Estimates list and 32-hex editor deep links resolve | `frontend/src/router.js:1-26` | `src/lib/router.ts` | `shell.routes.test.ts: estimates routes` | `full-parity: open list then persisted editor` |
| SHELL-003 | Data route resolves and restores after restart | `frontend/src/App.svelte:15-46` | `src/lib/stores/shell.ts` | `shell.restore.test.ts: data view` | `full-parity: restart; data view remains selected` |
| SHELL-004 | Search, current view, and estimate ID persist | `frontend/src/App.svelte:19-36` | Rust app-state commands | `state.shell.rs: latest state wins` | `full-parity: type/search/navigate/restart` |
| SHELL-005 | Header switches catalog, estimates, and data | `frontend/src/App.svelte:116-145` | `src/lib/components/AppHeader.svelte` | `AppHeader.test.ts: three navigation actions` | `full-parity: click each header control` |
| SHELL-006 | Recovery banner reports and retries imported or recovered changes | `frontend/src/App.svelte:67-109` | `OfflineBanner.svelte`, recovery replay command | `OfflineBanner.test.ts: imported recovery states` | `adversarial: stage recovery item, restart, retry` |
| SHELL-007 | Modal confirmation and Escape semantics remain | `frontend/src/App.svelte:116-145` | `Modal.svelte` | `Modal.test.ts: confirm cancel Escape` | `full-parity: delete modal keyboard flow` |
| SHELL-008 | Legacy priority, sync, and live tools stay external | `src/g2b_compare/web/app.py:135-168` | Data-route external links | `DataRoute.test.ts: external legacy URLs` | `legacy: links open separately hosted web tools` |

## Catalog and option browsing

| ID | Observable contract | Legacy evidence | Desktop seam | RED proof | Surface proof |
|---|---|---|---|---|---|
| CAT-001 | Query matches name, specification, and company | `frontend/src/routes/CatalogRoute.svelte:118-137` | `catalog::search_products` | `catalog_search.rs: three searchable fields` | `startup-catalog: enter known query; expected card visible` |
| CAT-002 | Four sorts preserve deterministic ordering | `frontend/src/routes/CatalogRoute.svelte:22,223-225` | `CatalogSort` enum | `catalog_search.rs: all sort variants` | `full-parity: switch each sort; first ID matches fixture` |
| CAT-003 | Pages contain 30 results and append near bottom | `frontend/src/routes/CatalogRoute.svelte:8-9,237-244` | paged search command | `catalog_search.rs: 30-row boundaries` | `full-parity: scroll; result count increases by 30` |
| CAT-004 | Appended pages deduplicate by product ID | `frontend/src/routes/CatalogRoute.svelte:60-78` | catalog store merge | `catalog.store.test.ts: duplicate page IDs` | `adversarial: overlapping pages show one card per ID` |
| CAT-005 | Long result lists render a virtual window | `frontend/src/routes/CatalogRoute.svelte:327-356` | `VirtualCatalog.svelte` | `VirtualCatalog.test.ts: bounded rendered cards` | `full-parity: deep scroll remains responsive and ordered` |
| CAT-006 | Product cards preserve all visible metadata | `frontend/src/routes/CatalogRoute.svelte:339-350` | `ProductCard.svelte` | `ProductCard.test.ts: metadata and fallback` | `startup-catalog: screenshot complete product card` |
| CAT-007 | G2B product links open externally | `frontend/src/routes/CatalogRoute.svelte:339-350` | typed external-open command | `ProductCard.test.ts: fixed G2B URL` | `full-parity: activate link; browser receives product URL` |
| CAT-008 | Selecting a product loads three relation groups | `frontend/src/routes/CatalogRoute.svelte:169-184` | relation query commands | `catalog_relations.rs: three categories` | `full-parity: select card; three tabs populated` |
| CAT-009 | Relation tabs keep independent search and pages | `frontend/src/routes/CatalogRoute.svelte:226-267` | relation store keyed by category | `relations.store.test.ts: isolated tab state` | `full-parity: search/page each tab; state retained` |
| CAT-010 | Relation search uses the legacy debounce behavior | `frontend/src/routes/CatalogRoute.svelte:26-40` | relation query effect | `relations.store.test.ts: latest query wins` | `adversarial: rapid typing shows only final query` |
| CAT-011 | Catalog view restores pages, selection, tabs, and scroll | `frontend/src/routes/CatalogRoute.svelte:276-316` | durable catalog-view state | `catalog.restore.rs: full view round trip` | `full-parity: restart; exact view position restored` |
| CAT-012 | Cached catalog remains visible while offline | `frontend/src/routes/CatalogRoute.svelte:122-168` | native catalog cache | `catalog_cache.rs: cached-first offline` | `adversarial: disconnect after warm search; cards remain` |
| CAT-013 | Uncached offline query reports unavailable stored results | `frontend/src/routes/CatalogRoute.svelte:122-137` | typed offline error | `CatalogRoute.test.ts: uncached offline copy` | `adversarial: cold offline query shows exact error state` |
| CAT-014 | Editor search returns preferred-company products and four sorts | `frontend/src/routes/estimate/catalog.js:13-27` | editor catalog command | `editor_catalog.rs: preferred ordering and sorts` | `full-parity: add overlay search matches fixture` |
| CAT-015 | Editor loads every option page and groups results | `frontend/src/routes/estimate/catalog.js:29-53` | complete options command | `editor_options.rs: multipage grouping` | `full-parity: select product; every grouped option appears` |
| CAT-016 | Add creates or reuses active draft with quantity one | `frontend/src/routes/CatalogRoute.svelte:204-220` | estimate add command | `estimate_add.rs: active draft reuse` | `full-parity: add two products; one active document` |
| CAT-017 | A document rejects the tenth line | `frontend/src/routes/CatalogRoute.svelte:204-220` | nine-line invariant | `estimate_add.rs: tenth line rejected` | `adversarial: ninth succeeds, tenth gives boundary message` |

## Estimate list, editor, and comparison table

| ID | Observable contract | Legacy evidence | Desktop seam | RED proof | Surface proof |
|---|---|---|---|---|---|
| EST-001 | New drafts use 32-hex IDs and timestamp titles | `frontend/src/routes/EstimatesRoute.svelte:12-18,55-58` | estimate repository create | `estimates.rs: generated identity/title` | `full-parity: create; title and ID format visible` |
| EST-002 | Empty new drafts stay hidden from the list | `frontend/src/routes/EstimatesRoute.svelte:36,50` | list query | `estimates.rs: empty draft hidden` | `full-parity: create/close empty; list unchanged` |
| EST-003 | Summaries reflect current documents saved in desktop `g2b.sqlite3` | `frontend/src/routes/EstimatesRoute.svelte:28-49` | estimate repository list | `estimates.rs: current saved summaries` | `adversarial: native save then offline list shows current revision` |
| EST-004 | Successful native saves remain visible offline without a replay item | `frontend/src/routes/EstimatesRoute.svelte:28-49` | estimate repository and list projection | `estimates.rs: saved locally with empty replay queue` | `adversarial: disconnect after save, then reopen list` |
| EST-005 | Delete requires confirmation and commits final removal in desktop `g2b.sqlite3` | `frontend/src/routes/EstimatesRoute.svelte:51,88-91` | native estimate delete command | `estimate_delete.rs: final local delete without tombstone` | `full-parity: confirm delete offline; document stays absent` |
| EST-006 | Title Enter/blur commits, Escape cancels, blank is ignored | `frontend/src/routes/estimate/TitleEditor.svelte:8-35` | title command/editor | `TitleEditor.test.ts: keyboard matrix` | `full-parity: exercise Enter, Escape, and blank blur` |
| EST-007 | Add overlay focuses, outside click/Escape closes | `frontend/src/routes/estimate/ProductSearch.svelte:57-128` | `ProductSearch.svelte` | `ProductSearch.test.ts: open/close/focus` | `full-parity: keyboard and outside-click flow` |
| EST-008 | Row removal persists and an empty saved document stays hidden from the list | `frontend/src/routes/EstimateRoute.svelte:139-168` | native estimate update and list projection | `estimate_lines.rs: last row saves empty document` | `full-parity: remove last row, save, then list stays empty` |
| EST-009 | Table shows selected plus A/B/C company/spec/ID/price | `frontend/src/routes/estimate/ComparisonTable.svelte:15-66` | comparison projection | `ComparisonTable.test.ts: four-column values` | `full-parity: screenshot populated comparison table` |
| EST-010 | Comparison IDs open fixed G2B links | `frontend/src/routes/estimate/ComparisonRow.svelte:52-132` | external-open command | `ComparisonRow.test.ts: comparison URLs` | `full-parity: open A/B/C IDs externally` |
| EST-011 | Specification tooltips support hover, focus, and Escape | `frontend/src/routes/estimate/ComparisonRow.svelte:52-132` | tooltip component | `ComparisonRow.test.ts: tooltip keyboard behavior` | `full-parity: focus tooltip then dismiss with Escape` |
| EST-012 | Clipboard copies TSV and falls back to hidden textarea | `frontend/src/routes/estimate/DocumentActions.svelte:14-42` | clipboard action | `DocumentActions.test.ts: primary and fallback` | `full-parity: copy; pasted text matches table TSV` |
| EST-013 | Clipboard feedback lasts for the legacy interaction interval | `frontend/src/routes/estimate/DocumentActions.svelte:14-42` | feedback state | `DocumentActions.test.ts: deterministic completion event` | `full-parity: success/failure feedback appears then clears` |
| EST-014 | Refresh requires saved lines and the current saved revision | `frontend/src/routes/EstimateRoute.svelte:107-138` | local comparison refresh transaction | `comparison_refresh.rs: refresh current saved snapshot` | `full-parity: save populated document, then refresh succeeds` |
| EST-015 | Refresh disables edits and rejects a result when the saved revision changed | `frontend/src/routes/EstimateRoute.svelte:117-168` | revision-checked local refresh command | `comparison_refresh.rs: current saved change wins` | `adversarial: another desktop save during refresh; stale result discarded` |
| EST-016 | External desktop saved/deleted events reconcile with current saved and unsaved changes | `frontend/src/App.svelte:47-65` | Tauri desktop event bus | `estimate_events.rs: saved/deleted current-change reconciliation` | `adversarial: event reloads saved state without overwriting an unsaved editor change` |
| EST-017 | Export appears only when every row has A/B/C comparisons | `frontend/src/routes/estimate/DocumentActions.svelte:71-76` | export readiness projection | `export_ready.rs: complete comparison requirement` | `full-parity: incomplete hidden, complete enabled` |
| EST-018 | Export filename and workbook match fixed template | `src/g2b_compare/web/estimate_routes.py:179-191` | Rust workbook exporter | `workbook_oracle.rs: fixture equality` | `full-parity: saved XLSX passes workbook oracle` |

## Data status, networking, and diagnostics

| ID | Observable contract | Legacy evidence | Desktop seam | RED proof | Surface proof |
|---|---|---|---|---|---|
| DATA-001 | Data view reports seven counts and readiness | `frontend/src/routes/DataRoute.svelte:8-31` | data status command | `data_status.rs: counts/readiness` | `full-parity: seven values match seeded DB receipt` |
| DATA-002 | Refresh error retains previously displayed counts | `frontend/src/routes/DataRoute.svelte:20-30` | data store | `DataRoute.test.ts: stale values on error` | `adversarial: force remote failure; counts remain` |
| DATA-003 | Local status works without network or API service | `src/g2b_compare/web/data_api.py:19-53` | local status repository | `data_status.rs: offline local read` | `startup-catalog: no Python server; ready status visible` |
| DATA-004 | Authenticated calls use only fixed official endpoints | `src/g2b_compare/sources/transport.py:83-178` | Rust remote client | `remote_client.rs: reject arbitrary host/key params` | `adversarial: malformed endpoint rejected before network` |
| DATA-005 | API failures preserve status/body without exposing key | `frontend/src/api.js:1-38` | typed redacted error | `remote_client.rs: status/body/redaction` | `adversarial: failed request shows safe actionable error` |
| DATA-006 | Sync and live diagnostics are explicit user actions | `src/g2b_compare/web/live_routes.py:77-104` | data commands | `data_commands.rs: explicit operation boundary` | `full-parity: run refresh and diagnostics from Data view` |
| DATA-007 | Embedded key never enters JavaScript, DB, logs, or arguments | `src/g2b_compare/sources/transport.py:139-178` | Rust build/remote boundary | `credential_boundary.rs: artifact and log scans` | `startup-catalog: API action works without runtime env` |

## Offline persistence and replay

| ID | Observable contract | Legacy evidence | Desktop seam | RED proof | Surface proof |
|---|---|---|---|---|---|
| OFF-001 | Shell, catalog view, and active estimate persist | `frontend/src/lib/db.js:1-35` | app-state tables | `app_state.rs: state round trips` | `full-parity: restart preserves exact state` |
| OFF-002 | Catalog cache has stable versioned keys and no implicit TTL | `frontend/src/routes/estimate/catalog.js:3-53` | catalog cache table | `catalog_cache.rs: key/version semantics` | `adversarial: cached result survives clock advance` |
| OFF-003 | A new empty draft creates no recovery replay item | `frontend/src/lib/db.js:69-85` | native estimate create and recovery queue boundary | `estimate_state.rs: empty draft leaves replay queue empty` | `full-parity: create empty draft; retry count stays zero` |
| OFF-004 | A successful native edit is final locally and creates no recovery replay item | `frontend/src/lib/db.js:69-85` | native estimate update and recovery queue boundary | `estimate_state.rs: offline save leaves replay queue empty` | `adversarial: save offline, restart, and read saved change` |
| OFF-005 | Imported replay applies only when its base revision matches the current saved document | `frontend/src/lib/db.js:138-160` | revision-checked recovery materialization | `estimate_state.rs: current saved change is preserved` | `adversarial: newer saved change rejects stale imported change` |
| OFF-006 | Replay failure keeps the imported recovery change and an actionable error | `frontend/src/lib/db.js:162-170` | recovery failure transition | `estimate_state.rs: imported change survives failure` | `adversarial: failed recovery replay survives restart` |
| OFF-007 | Successful native delete is final and creates no tombstone or recovery replay item | `frontend/src/lib/db.js:121-136` | native estimate delete and recovery queue boundary | `estimate_delete.rs: final local delete` | `adversarial: delete offline, restart, and verify absence` |
| OFF-008 | Recovery replay is globally serialized and materializes each imported change exactly once | `frontend/src/lib/sync.js:7-45` | recovery replay coordinator | `replay.rs: serialized exact-once local materialization` | `adversarial: duplicate retry produces one g2b.sqlite3 change` |
| OFF-009 | Bundled shell starts fully offline | `src/g2b_compare/web/frontend_dist/sw.js:1-66` | packaged WebView assets | `bundle_contract.rs: no remote UI assets` | `startup-catalog: disconnect before launch; shell renders` |

## Database lifecycle, capability, and packaging

| ID | Observable contract | Legacy evidence | Desktop seam | RED proof | Surface proof |
|---|---|---|---|---|---|
| DB-001 | First launch copies a valid seed exactly once | `scripts/build-portable-package.ps1:30-37` | database bootstrap | `seed_database_is_copied_once_without_overwrite` | `startup-catalog: AppData DB created and populated` |
| DB-002 | Re-launch never overwrites user-modified data | `src/g2b_compare/db/migrate.py:36-81` | database bootstrap | `seed_database_is_copied_once_without_overwrite` | `adversarial: mutate row, restart, mutation remains` |
| DB-003 | Concurrent first starts publish one valid database | `src/g2b_compare/db/connection.py:14-105` | startup lock/atomic rename | `concurrent_first_start_installs_one_valid_database` | `adversarial: parallel launch leaves one integrity-clean DB` |
| DB-004 | Migrations are ordered, transactional, and checksum locked | `src/g2b_compare/db/migrate.py:36-81` | migration runner | `migrations.rs: order rollback checksum` | `adversarial: drifted migration fails before UI ready` |
| DB-005 | Writable DB uses WAL, FK, and five-second timeout | `src/g2b_compare/db/connection.py:14-105` | connection factory | `connection.rs: required pragmas` | `startup-catalog: DB pragma receipt matches` |
| DB-006 | Read-only access enables query-only mode | `src/g2b_compare/db/connection.py:14-105` | read connection | `connection.rs: writes rejected` | `adversarial: read path cannot mutate DB` |
| PKG-001 | Desktop AppData and identifier are distinct from legacy | `src/g2b_compare/web/app.py:114-122` | Tauri identifier/path resolver | `bundle_contract.rs: distinct identity/path` | `startup-catalog: receipt contains desktop-only path` |
| PKG-002 | Capability and CSP expose only required local authority | Tauri plan security contract | capability/config validator | `capability_contract.rs: forbidden permissions/sources` | `adversarial: generic fs/http/shell invokes unavailable` |
| PKG-003 | Release build fails when embedded key is absent | User-approved packaging contract | `build.rs` | `release_build_without_key_fails` | `installer: keyless release command exits nonzero` |
| PKG-004 | Per-user NSIS installs and launches without Python | Tauri plan installer contract | bundle config | `bundle_contract.rs: NSIS/resource metadata` | `startup-catalog: installed EXE works with Python stopped` |
| PKG-005 | Legacy web app remains independently runnable on 8765 | `scripts/start.py:24-29,93-133` | isolation contract | `legacy_status_hash` | `legacy: curl 200 plus Chrome screenshot; port cleanup` |

## Completion rule

The binding machine-readable manifest is `docs/tauri-parity-evidence-manifest.json`.
Its deterministic contract test rejects duplicate/missing IDs and passing rows
whose test, gate, receipt, or artifact is unverifiable.

All IDs above must appear exactly once in the machine validation manifest.
Every row must have non-empty values in all six columns. The desktop rewrite is
not complete while any row lacks GREEN test output, packaged surface evidence,
or a cleanup receipt.
