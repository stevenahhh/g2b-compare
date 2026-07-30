# MAIN-PROCESS SECURITY BOUNDARY

## STARTUP

- Register the privileged `app` scheme before readiness.
- Enable Electron sandboxing, register `app://app`, verify official resources, then
  create the window and IPC handlers.
- A failed official-data verification must prevent a usable window from opening.

## PROTOCOL

- `APP_ORIGIN` is exactly `app://app`.
- Resolve decoded paths beneath the canonical renderer root; reject traversal, absolute
  paths, ports, credentials, unknown extensions, and missing targets.
- Serve only GET/HEAD with no-store, strict local-only CSP, nosniff, and allowlisted MIME.
- Do not add network origins, `unsafe-eval`, form targets, frames, or objects to the CSP.

## WINDOW HARDENING

- Keep sandbox and context isolation enabled; Node integration and webviews disabled.
- Deny navigation, redirects, new windows, downloads, and all permission requests/checks.
- Never expose `ipcRenderer`, filesystem APIs, or mutable privileged objects from preload.

## IPC CONTRACT

- Fixed channels: `dialog`, `import`, `export`, `readSeed`, `getBuildInfo`.
- Validate both request and response with the channel-specific Zod schema.
- Require the live main window, matching webContents, `app://app` frame, and exact
  process/routing identity before invoking an operation.
- Internal exceptions become stable bridge error codes; renderer-visible text must not
  contain paths, stack traces, provider data, or implementation details.
- File selection issues one-shot 120-second capabilities bound to operation and frame.
  Consumption deletes the capability; wrong kind/frame, expiry, or reuse fails closed.

## ANTI-PATTERNS

- No renderer-supplied arbitrary path may reach import/export directly.
- No test dependency injection seam may remain in the production bundle.
- No weakening sender checks for E2E convenience; use the dedicated test entry points.

## VERIFICATION

```powershell
npm run typecheck
npm run test:security
npm run test:e2e
```

Relevant contracts live in `tests/security/`, `tests/e2e/native-workflow-test-*.ts`,
and package-level production graph tests.
