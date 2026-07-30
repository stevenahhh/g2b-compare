# PYTHON TEST KNOWLEDGE

## ORGANIZATION

The tree mirrors backend domains (`db`, `sync`, `services`, `web`, `ranking`,
`evaluation`, and others) plus cross-cutting `acceptance`, `performance`,
`security`, `live`, and `tools` lanes.

## CONVENTIONS

- Pytest root is `tests`; `src` is on `pythonpath`.
- Strict config/markers and strict asyncio are enabled; every warning is an error.
- Use `tmp_path` for databases, raw stores, workbooks, indexes, and exports.
- Build database fixtures through production migrations and repository helpers.
- Support/scenario modules are explicit (`*_scenarios.py`, `*_support.py`, fixtures);
  this repository intentionally has no central `conftest.py`.
- Acceptance scenarios compare actual exception class/message to
  `tests/acceptance/expected-failures.json` and preserve provenance receipts.
- Test a behavior at the lowest useful boundary, then add acceptance/browser coverage
  only when the user-visible contract crosses layers.
- Subscribe to the exact event/state before triggering async behavior; await it with
  a bounded timeout. Fixed sleeps and timing-luck polling are forbidden.
- Freeze clocks/randomness/order when they affect an assertion.

## SPECIAL LANES

| Lane | Location | Purpose |
|---|---|---|
| External contracts | `tests/contracts/`, `tests/live/` | Quotas, capture, provider safety |
| Release invariants | `tests/db/`, `materialize/`, `sync/` | Atomicity and resume behavior |
| Held-out evaluation | `tests/evaluation/` | Immutable artifact and threshold gates |
| Performance | `tests/performance/` | Controlled corpus and process evidence |
| Browser/SPAs | `tests/web/` | ASGI plus Playwright user journeys |
| Security | `tests/security/`, observability tests | Integrity and secret boundaries |

## ANTI-PATTERNS

- Do not weaken, delete, skip, or xfail a failing contract to obtain green.
- Do not read/write the developer `.g2b` database from tests.
- Do not mock away the persistence/integration boundary being asserted.
- Do not pin exact prompt/prose text when structured behavior is the contract.
- Do not call domain “coverage” metrics code-coverage; no code-coverage threshold exists.

## COMMANDS

```powershell
uv run pytest -q tests/<domain>/<test_file>.py -k "<behavior>"
uv run pytest -q tests/<domain>
uv run pytest -q
uv run ruff check tests
uv run basedpyright
```
