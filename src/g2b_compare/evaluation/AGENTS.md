# EVALUATION EVIDENCE RULES

## OVERVIEW

This directory validates immutable E0 packages, binds predictions to exported
source identities, computes deterministic metrics, and enforces release thresholds.

## TRUST BOUNDARIES

- `e0-v1`: externally authored relevance records with manifest hashes/counts/strata.
- `e0-export-v1`: generated unlabeled export; never evidence of ranking quality by itself.
- `e0-strict-v1`: external gold explicitly bound to the source export and held-out pool.
- Declared files must be safe relative paths; absolute paths and `..` escape fail closed.

## CONVENTIONS

- Parse manifests/rows with frozen Pydantic models and reject extra fields where specified.
- Verify SHA-256, file presence, row counts, strata, pool identity, and duplicate keys
  before computing metrics.
- Use `Decimal` for scores, thresholds, and reported metrics; preserve exact rounding rules.
- Sorting and candidate identity must be byte-stable and platform-independent.
- Strict evaluation consumes actual prediction artifacts; it does not run a hidden model.
- Held-out constraints and thresholds in `runner.py` are decision contracts, not tuning knobs.
- Preserve source-export and materialization identities in every evaluation artifact.

## ANTI-PATTERNS

- Never fabricate, infer, repair, relabel, or reorder external gold.
- Never use synthetic fixtures/receipts to claim production quality.
- Never mix train/tuning rows into the held-out decision.
- Never convert validation failures into warnings or add epsilon tolerance to exact gates.
- Never silently filter prediction rows outside the declared judged pool.

## WHERE TO TEST

| Change | Tests |
|---|---|
| Package/schema/hash | `tests/evaluation/test_e0_*.py`, `tests/unit/test_e0_schema.py` |
| Metrics/thresholds | `tests/evaluation/test_metrics.py`, `test_runner.py` |
| Export/source binding | `tests/evaluation/test_e0_export.py`, strict binding tests |

```powershell
uv run pytest -q tests/evaluation tests/unit/test_e0_schema.py
uv run basedpyright
```

Developer entry points live in `tools/export_e0.py` and `tools/validate_e0.py`;
inspect their CLI help before invoking them on non-fixture data.
