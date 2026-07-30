# ELECTRON ESTIMATOR KNOWLEDGE

## OVERVIEW

Independent Windows Electron package for verified estimate calculation and native/
legacy workbook publication. It is strict ES2024 ESM with Zod trust boundaries.

## STRUCTURE

| Area | Responsibility |
|---|---|
| `src/domain/` | Pure estimate, money, provenance, validation rules |
| `src/official/` | Verified official data repository, pricing, selection |
| `src/native/` | New workbook calculation and sheet generation |
| `src/legacy/` | Existing OOXML inspection, patch, validation, atomic export |
| `src/main/` | Privileged startup, protocol, IPC, capabilities |
| `src/preload/` | Frozen typed `window.estimator` bridge |
| `src/renderer/` | Workbench state/view and design contract |
| `src/workflows/` | Native and legacy user-flow orchestration |
| `resources/` | Packaged official/legacy manifests, data, observations, sources |
| `tests/` | Unit, integration, security, contract, E2E, renderer lanes |

## CONVENTIONS

- `tsconfig.json` enables strict, noUncheckedIndexedAccess, exact optional types,
  verbatim modules, and no switch fallthrough.
- Parse IPC, files, manifests, and official records with Zod before use.
- Verify official data before creating the first BrowserWindow; fail closed on mismatch.
- Keep domain calculations deterministic and free of Electron/renderer dependencies.
- Renderer imports neither Node I/O nor privileged Electron APIs; preload exposes only
  the frozen validated bridge.
- `DESIGN.md` and `src/renderer/design-contract.ts` must remain equivalent.
- Source manifests and production observations require real provenance, not synthetic rows.

## GENERATED AND PACKAGE BOUNDARIES

- `npm run build` regenerates `dist/main`, `dist/preload`, and `dist/renderer`.
- `scripts/assert-build.mjs` is the exact disposable `dist` inventory oracle.
- `electron-builder.yml` packages only allowlisted `dist`, resource, and package files.
- ASAR must not contain tests, TypeScript, source maps, datasets, caches, or secrets.
- `release/`, `test-results/`, verification reports, and evidence are generated.

## COMMANDS

```powershell
npm ci
npm run typecheck
npm run build
npm run test:unit
npm run test:integration
npm run test:security
npm run test:e2e
npm run verify:all
```

`verify:all` is the handoff gate: all stages execute, tests have zero failed/skipped/
pending, package smoke markers pass, no shared evidence is mutated, and cleanup audits pass.
