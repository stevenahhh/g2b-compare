---
slug: g2b-similar-product-search
status: reviewing
intent: clear
review_required: true
pending-action: write .omo/plans/g2b-similar-product-search.md
approach: local desktop-first FastAPI/Jinja2/vanilla-JS application backed by SQLite FTS5 and checkpointed OpenAPI snapshots; deterministic Korean specification and price comparison; no shop-page scraping or inferred option parentage
---

# Draft: g2b-similar-product-search

## Components (topology ledger)

| id | outcome | status | evidence path |
| --- | --- | --- | --- |
| C1 | Approved OpenAPI responses are captured safely, paged, checkpointed, and normalized without exposing the service key | active | `.omo/ulw-research/20260714-095047/verify-api-contract.md:12` |
| C2 | Product, price, individual attribute, option-role, relation provenance, and sync state are reproducible in SQLite | active | `.omo/ulw-research/20260714-095047/verify-data-coverage.md:9` |
| C3 | Korean option text and numeric/unit specifications become versioned derived features while raw source text is preserved | active | `.omo/teams/team-c4bb5e40/artifacts/similarity-retrieval.md:18` |
| C4 | Exact product/category membership and deterministic similarity ranking return three honest comparator slots per match | active | `.omo/teams/team-c4bb5e40/artifacts/similarity-retrieval.md:38` |
| C5 | A desktop-first form and result list expose all matches, per-match comparators, score reasons, freshness, and G2B verification links | active | `.omo/ulw-research/20260714-095047/SYNTHESIS.md:28` |
| C6 | Local operation, security, performance, evaluation, and release checks run without human intervention | active | `.omo/ulw-research/20260714-095047/SYNTHESIS.md:36` |

## Open assumptions (announced defaults)

| assumption | adopted default | rationale | reversible? |
| --- | --- | --- | --- |
| Deployment | Single-user Windows local web app bound to `127.0.0.1`; no authentication UI | Approved option; smallest secure desktop-first surface | yes |
| Data access | Apply for dataset 15129417 and block structured-attribute enrichment until a sanitized authorized success fixture exists | Public schema does not expose exact item fields | yes |
| Price representation | Preserve every current contract offer; for a product use the lowest positive active `cntrctPrceAmt` with its explicit unit as the display/comparison price, while retaining all offers for audit | Deterministic and buyer-oriented; avoids mixing historical `prdctUprc` | yes, versioned policy |
| Option relation | Treat option-role products as independent candidates; import an exact parent relation only with a stable source key or source-labeled curated workbook mapping | No documented parent key exists | yes |
| Search membership | Canonical exact category code and normalized exact product-name key; aliases require reviewed table entries | Prevents wrong-kind comparison | yes, via versioned broad-search mode later |
| Test strategy | TDD with pytest, Hypothesis, respx, and Playwright; live API tests opt-in and redacted | User approved; protects deterministic ranking and external boundaries | yes |

## Findings (cited - path:lines)

- Current service base, GET/JSON/XML contract, paging, quota evidence, and retired legacy family: `.omo/ulw-research/20260714-095047/verify-api-contract.md:12-22`.
- Core catalog, price, option-role, and error/freshness fields: `.omo/ulw-research/20260714-095047/verify-api-contract.md:24-69`.
- Exact parent-child option link is not generically available: `.omo/ulw-research/20260714-095047/verify-api-contract.md:53-62`.
- Required edge behavior for no result, missing candidates, missing price, bad transport, pagination, and stale cache: `.omo/ulw-research/20260714-095047/verify-data-coverage.md:26-41`.
- Shared page is a WebSquare shell with transient keys and is suitable only as an outbound verification link: `.omo/ulw-research/20260714-095047/verify-shop-access.md:3-10`.
- Approved architecture, data flow, UI, security, and latency targets: `.omo/ulw-research/20260714-095047/SYNTHESIS.md:3-47`.
- Deterministic feature formula, missingness, tie order, and exact three-slot behavior: `.omo/teams/team-c4bb5e40/artifacts/similarity-retrieval.md:79-206`.

## Decisions (with rationale)

- Use Python 3.12+, FastAPI, Jinja2, minimal HTMX/vanilla JavaScript, and SQLite WAL/FTS5. One process and server-rendered HTML minimize desktop startup and UI complexity.
- Keep API keys in environment variables only. CLI sync is the only mutation entry point; the web process is read-only.
- Perform an authenticated contract-capture spike first and commit sanitized fixtures, never credentials or request URLs containing keys.
- Ingest the three contract catalog operations, shopping-mall registration history, delivery-request detail for option roles, and individual attributes. Do not ingest Venture Nara or aggregate procurement operations for the requested search path.
- Preserve raw provider records and version every derived normalization/ranking artifact.
- Use ranking version `v1`: lexical 0.35, fuzzy 0.20, structured numeric/unit 0.35, comparable price 0.10; anchor-directed missingness and six-decimal round-half-even tie handling.
- Return every search match. Each match has exactly three comparator slots; null slots use `insufficient_candidates` and zero-evidence rankings are labeled `no_comparison_evidence`.
- Generate the G2B share URL only from validated contract item management identifiers discovered by the contract spike; never persist transient `bodyDataKey` or `key` parameters.

## Scope IN

- Project bootstrap, typed configuration, schema migrations, fixtures, unit/integration/E2E tests, and Windows run instructions.
- Safe OpenAPI adapters, pagination, retry/backoff, quota accounting, checkpoints, raw snapshots, and last-known-good refresh.
- Canonical product/offer/attribute/option-role/provenance model and read-only workbook fixture extraction.
- Korean text normalization, number/unit parsing, FTS candidate retrieval, deterministic ranker, explanations, and evaluation set tooling.
- Desktop-first search form, all-match result list, three comparators per match, freshness/errors, and outbound G2B links.
- Local performance, security, data-quality, and release verification.

## Scope OUT (Must NOT have)

- No scraping or browser automation as an ingestion source.
- No cloud deployment, public binding, multi-user authentication, PostgreSQL, Electron/native wrapper, or automatic purchasing.
- No embeddings, LLM ranking, learning-to-rank, fuzzy category membership, price imputation, or inferred option parent links.
- No mutation of the three source XLSX workbooks or storage of the raw credential-bearing account attachment.
- No use of retired `ShoppingMallPrdctInfoService02..06` endpoints.

## Open questions

None. Authorized success payload details are an implementation spike with a fail-closed acceptance gate, not an owner decision.

## Approval gate
status: approved
approved-at: 2026-07-14 Asia/Seoul
approval-message: `승인`
pending-action: generate and high-accuracy-review `.omo/plans/g2b-similar-product-search.md`

## Review receipts

### Metis

- Session: `/root/metis_gap_review`
- Result: initial NO-GO against the empty skeleton.
- Folded fixes: authorized-success prerequisite, five ShoppingMall plus one attribute operation scope, quota/sync/tombstone contract, contextual option roles, exact ranking/three-slot formula, TDD failure matrix, UI states, FTS5 gate, outbound-link fallback, XLSX limitation, localhost-only deployment.

### High-accuracy round 1

- Native Momus session: `/root/momus_plan_review`
- Native result: `REVISE` with 12 findings.
- Independent Codex CLI: session `019f5ec5-1055-7b63-ad4d-a98c1099704a`, model `gpt-5.6-sol`, reasoning `xhigh`, isolated read-only workspace, result `REVISE` with 12 findings.
- Fix summary: added an exact operation matrix; made authorized catalog and attribute success a hard gate; defined per-operation source snapshots, copy-forward overlays, source-scoped tombstones, content-addressed raw storage, source identities, quota reservations including retries, KST/rolling ledgers, regex-v1 tokenizer, complete structured matching/coverage/sort semantics, category/unit/tolerance request rules, option/relation UI provenance, state/freshness/no-bold contracts, exact per-todo RED/GREEN harness, reproducible performance boundaries, official host allowlist, runtime secret scans, and exact final verifier commands.
- Status: round 2 required; no approval claim yet.

### High-accuracy round 2

- Native Momus session: `/root/momus_plan_review_2`.
- Native result: `REVISE` with 11 findings.
- Independent Codex CLI: session `019f5ed4-03c8-7a62-84d6-e306b1420c7e`, model `gpt-5.6-sol`, reasoning `xhigh`, isolated read-only workspace, result `REVISE`.
- Review-environment correction: the independent workspace omitted the actual `docs/reference/` and `dataset/` inputs, so its missing-input finding was a reviewer workspace defect rather than a project defect. The next isolated review must include byte copies of those sources.
- Fix summary: separated content-addressed raw blobs from page mappings; defined five-source catalog generations and same-generation attribute successor semantics; made materialization uniqueness version-aware; fixed the bounded P1-P5 probe order and retry charging; moved contract capture behind the quota ledger; defined component coverage; added complete price and category validation matrices; expanded option roles to event-level provenance; fixed UI token priority and no-bold canaries; pinned entry-point/test plugins; made the 50k corpus and process-cold/warm-OS-cache measurements reproducible; required a 200-anchor two-assessor adjudicated gold set; fixed regex-v1 quantity/context/ranking boundaries; and made RED/GREEN plus F1-F4 artifact auditing machine-verifiable.
- Status: fresh round 3 required; no approval claim yet.

### High-accuracy round 3

- Native Momus session: `/root/momus_plan_review_3`.
- Native result: `REVISE` with 13 findings.
- Independent Codex CLI: session `019f5ee5-43a2-7463-81e4-a3fcced91c4f`, model `gpt-5.6-sol`, reasoning `xhigh`, isolated read-only workspace with copied DOCX, redacted reference, all three XLSX, research evidence and similarity artifact; result `REVISE` with 11 unique findings.
- Fix summary: added cross-generation unchanged-product attribute carry-forward and TTL queueing; window-aware pages, operation-scoped request identities, media-neutral raw storage and active origin retention; canonical catalog/materialization JCS digests; an executable discovery/verification probe state machine; complete in-plan ranking and hand vectors; protect-before-casefold parser order; combined category/price validation precedence; primary/predicate UI truth rules and exhaustive no-bold checks; all-node RED failure manifests; exact F1-F4 receipt schemas; exact 200×10 assessor protocol and 500-span parser gold; exact perf-v1 product/query generator; namespaced offer and attribute raw provenance; SHA/sheet/cell-bound workbook relation grammar with 12 accepted and 3 quarantined rows; exact share-link template and fallback; atomic concurrent/crash quota reservation tests; and corrected Todo 2/4 dependencies.
- Status: fresh round 4 required; no approval claim yet.

### High-accuracy rounds 4-12

- Native reviewers: `/root/momus_plan_review_4` through `/root/momus_plan_review_12`.
- Independent Codex CLI rounds were run from isolated ASCII-path workspaces containing the exact plan, research evidence, preserved DOCX, and all three XLSX files.
- Results: successive `REVISE` findings were folded into the plan. The corrections closed attribute full-replacement/provenance, quota bootstrap, validation priority, E0 ownership and sampling, TF-IDF configuration/corpus/bytes, UI state algebra, release atomicity, relation snapshots, hard-kill recovery, multi-semantic parser gold, judged-pool metrics, canonical bundle/relation/cache SHA, and attempt-isolated cache retries.
- Round 4 independent process ended without a verdict file and was never counted as approval. Later failed/stale CLI attempts were likewise not counted.

### High-accuracy final round 13

- Reviewed plan SHA-256: `5d6fad54707948883455b66485d0e5e8b2c9b8ff0dcf35982c3582727dfa6f66`.
- Native Momus session: `/root/momus_plan_review_13`.
- Native result: `VERDICT: OKAY`.
- Independent Codex CLI session: `019f5f4d-92cf-7510-91de-f28a479808e8`, model `gpt-5.6-sol`, reasoning `xhigh`, isolated workspace with source hashes preserved.
- Independent result: `VERDICT: OKAY`.
- Structural audit: exact 16 todos; each has References, Acceptance criteria, QA scenarios, and Commit; required heading order preserved; no bold, TODO, TBD, or placeholder text.
- Final status: approved plan is decision-complete and ready for execution. No product implementation has started.
