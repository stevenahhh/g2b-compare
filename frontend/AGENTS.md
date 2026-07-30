# SVELTE FRONTEND KNOWLEDGE

## OVERVIEW

Private Svelte 5/Vite SPA embedded in the Python service. `App.svelte` owns shell
navigation, restored state, connectivity, estimate revision signals, and route views.

## STRUCTURE

| Area | Responsibility |
|---|---|
| `src/routes/` | Catalog, estimate list/editor, and data status screens |
| `src/components/` | Shared modal/offline presentation |
| `src/lib/db.js` | IndexedDB cache, estimate, and app-state transactions |
| `src/lib/sync.js` | Serialized pending estimate upload/delete |
| `src/router.js` | Core/deep-link parsing and opt-in SPA navigation |
| `src/styles/` | Tokens, shell, screens, responsive rules |
| `public/sw.js` | Service worker copied into the production bundle |

## STATE AND SYNC CONTRACT

- Use Svelte 5 runes in components and pass route data/actions through props.
- IndexedDB version 1 has exactly `catalog_cache`, `estimates`, and `app_state` stores.
- Local estimates are latest-write state; stale sync completion must not clear newer edits.
- Never-synced empty/deleted drafts may disappear locally; synced deletes remain pending tombstones.
- `syncPendingEstimates` serializes runs and records stable per-document failures.
- SSE `estimate-saved`/`estimate-deleted` events invalidate visible estimate data.
- Legacy `/live`, `/priority`, and `/sync` links remain outside SPA interception.
- Preserve offline editing when persistence or the server is temporarily unavailable.

## UI CONVENTIONS

- `../DESIGN.md` is the token/layout/accessibility contract.
- Light mode only; CJK system fonts, visible focus, semantic landmarks, 44px primary controls.
- Keep catalog/document data scannable; retain dedicated scroll regions and tabular figures.
- Preserve keyboard/Escape/focus behavior for overlays and full-spec tooltips.

## BUILD AND TEST

```powershell
npm ci
npm test -- --run
npm run build
npm run dev
```

Vitest is intentionally limited to one worker. Add tests beside `api.js`, `router.js`,
or `lib/*.js`; use `fake-indexeddb` for persistence behavior.

## GENERATED BOUNDARY

`npm run build` replaces `../src/g2b_compare/web/frontend_dist/`. Never edit that
directory directly. After a build, run the Python SPA delivery tests as well.
