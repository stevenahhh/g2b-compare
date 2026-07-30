# ELECTRON TEST KNOWLEDGE

## LANES

| Lane | Location/config | Contract |
|---|---|---|
| Unit | `tests/unit/`, `vitest.config.ts` | Domain, official, toolchain, verification |
| Integration | `tests/integration/`, integration config | OOXML/native workbook and recovery |
| Security | `tests/security/`, security config | Window, IPC, capabilities, production graph |
| Node contracts | `tests/contracts/`, `tests/legacy/` | Build/design/process/mutation contracts |
| Electron E2E | `tests/e2e/`, root Playwright config | Native and legacy user workflows |
| Renderer | `tests/renderer/`, local Playwright config | UI behavior and design primitives |

## FIXTURES AND ISOLATION

- Use package-local fixtures and verified resource manifests; production rows require
  authentic provenance, not synthetic substitutes.
- Create workbooks, destinations, journals, and evidence in test-owned temp roots.
- Tests that launch children must terminate the owned process tree and prove cleanup.
- Crash/mutation tests assert both negative publication and recovery receipts.
- Playwright is serial (`fullyParallel: false`) and `forbidOnly: true`.
- Subscribe/assert observable UI or process state; do not synchronize by fixed sleeps.

## FULL MATRIX

`npm run verify:all` runs exactly:

1. `typecheck`
2. `build`
3. `unit`
4. `integration`
5. `security`
6. `data-contracts-legacy`
7. `electron-native-legacy`
8. `electron-renderer`
9. `package-asar`
10. `artifact-oracle`
11. `cleanup-audit`

The evidence root must be fresh and empty. Success requires every stage, at least one
test, zero failed/skipped/pending, no writes to shared default evidence, package smoke
markers, the regression oracle, and cleanup audit.

## COMMANDS

```powershell
npm run test:unit
npm run test:integration
npm run test:security
npm run test:e2e
npm run verify:all
```

Do not weaken exact `dist`/ASAR inventories, add `.only`/skip/todo cases, reuse stale
evidence, or leave temp files/processes after a lane completes.
