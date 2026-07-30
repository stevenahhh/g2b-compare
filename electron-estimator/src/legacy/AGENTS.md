# LEGACY WORKBOOK BOUNDARY

## PIPELINE

```text
inspect -> patch plan -> OOXML patch -> validation report
        -> durable staging -> atomic workbook/sidecar publish -> cleanup
```

Keep `inspect/`, `patch/`, `validation/`, and `export/` responsibilities separate.

## INPUT AND PATCH RULES

- Treat XLSX as an untrusted ZIP/XML package; formula text is data, never executable logic.
- Inspection must reject malformed central directories, paths, XML, workbook structure,
  or unsupported profile evidence.
- Drive edits from the selected versioned legacy manifest and explicit cell plan.
- Preserve the source workbook byte-for-byte; pin and recheck its SHA-256.
- Do not invent cells, extend the template, or patch outside declared ranges.
- Generated output must satisfy the no-VBA, no-external-link, and no-defined-name contracts.

## ATOMIC EXPORT

- Preflight source/destination identity and keep the journal root outside the destination.
- Recover interrupted transactions before accepting a new export.
- Build workbook and validation report as one verified pair.
- Write and verify durable temporary files before publication.
- Journal each state transition; publish sidecar then workbook through the staged protocol.
- Recheck source SHA immediately before and after publication.
- On failure, remove partial publication and report an explicit cleanup receipt.
- Do not return success while a transaction journal remains.

## ANTI-PATTERNS

- Never overwrite or “repair” the source template.
- Never publish a workbook without its matching validation sidecar.
- Never catch an arbitrary failure and leave temporary/journal files unaccounted for.
- Never replace manifest/profile checks with filename heuristics.
- Never weaken crash, mutation, underfill, or adversarial ZIP tests.

## VERIFICATION

```powershell
npm run test:integration
npm run test:e2e
npm run verify:all
```

Focused coverage is under `tests/integration/`, `tests/legacy/`, and legacy E2E specs.
