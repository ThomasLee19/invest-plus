<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-01 | Updated: 2026-07-01 -->

# src

## Purpose
Frontend application source. Entry → router → page-level features. The core
feature is the chat page, which consumes the backend SSE stream and renders both
the answer and the model's thinking chain.

## Key Files
| File | Description |
|------|-------------|
| `main.tsx` | App bootstrap (router, i18n, global styles). |
| `App.tsx` | Root component. |
| `i18n.tsx` | i18n setup (zh/en). |
| `index.css` / `antd.scss` | Global + antd theming. |
| `vite-env.d.ts` | Vite ambient types. |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `pages/` | Route targets: `index/`, `chat/`, `repository/`, `404.tsx` |
| `components/` | Reusable UI: `header-bar`, `hot-questions`, `markdown`, `page-layout`, `sender`, `icons` |
| `styles/` | `tokens.css` (single source of truth) + `tokens.ts` (JS mirror for antd/inline styles) |
| `layout/` | `base/` app shell + nav |
| `router/` | `routes.tsx` (route table), `index.tsx` (browser router), `hook.ts`, `context.ts` |
| `store/` | Valtio stores: `session`, `user`, `device`, `storage`, plus `valtio-persist` helper |
| `api/` | Axios-based API client + typed endpoints (`session`, `repository`) and a request plugin chain under `request/` |
| `utils/` | `usePageTransport`, `useSendMessage` (SSE consumption), misc helpers |
| `configs/` | `enum.ts`, `index.ts` app constants |
| `assets/` | SVG/PNG assets grouped by feature (`chat`, `layout`, `repository`, …) |

## For AI Agents

### Working In This Directory
- **Routes** (`router/routes.tsx`): `/` (Index), `/chat/:id` (Chat),
  `/repository`; everything else → 404. All wrapped in `BaseLayout`.
- **SSE shape** consumed by `pages/chat/index.tsx`:
  `{ role: 'agent' | 'assistant', content, thinking?: boolean }`.
- **`documents` is a LIVE branch — do not treat it as dead.** An earlier version
  of this file listed it alongside the dead branches; that was wrong and cost a
  planning cycle. The full chain, verified end to end:
  `backend/app/service/agent/agent.py:1406` yields the `documents` event →
  `pages/chat/index.tsx:221-223` writes it to `target.reference` →
  `pages/chat/component/result.tsx:367` renders the source list, and the inline
  `[1]` citation tokens come from the `marked` extension in `result.tsx:88-120`.
  Styles live in `result.module.scss` under `.chat-message-result__source`.
  Confirmed empirically: a live session's SSE stream carries `documents` with 11
  document entries.
- **Genuinely dead branches:** `recommended_questions`, `image_results`,
  `video_results`. `grep -rn 'image_results\|video_results\|recommended_questions'
  backend/` returns zero hits, so `result.tsx:215/238/272` never render at
  runtime. Their styles are kept (and token-ised) only because deleting them
  would also mean deleting JSX in `result.tsx` and six i18n keys — a functional
  change disguised as a styling one. Don't build on them without a backend change.
- Use the `@/` alias for imports (→ `src/`). State lives in Valtio stores under
  `store/`; don't reach for React Context for shared state.
- API calls go through `api/` (axios instance + plugin chain in `api/request/`),
  not raw `fetch`, except the SSE stream which is handled in `utils/useSendMessage`.

### Testing Requirements
No unit tests. Validate with `npm run lint` and `npm run build` from `frontend/`,
then exercise the page in `npm run dev`.

Three additional gates live in `frontend/scripts/` — run them from `frontend/`:

| Script | Checks |
|--------|--------|
| `check-tokens.mjs` | `tokens.css` ↔ `tokens.ts` key/value parity; forbids `var(` in the TS mirror |
| `check-i18n.mjs` | `zh` and `en` top-level key sets are identical |
| `check-hardcoded-colors.mjs` | no colour literals in property values under `src/` |

Verification greps must be run **from the repo root** — `git grep`'s pathspec is
cwd-relative, so `git grep … -- frontend/src` from inside `frontend/` silently
returns zero rows instead of erroring.

### Common Patterns
- Component-per-folder with co-located `index.tsx` + `index.module.scss`.
- CSS Modules (`*.module.scss`) for component styles; global SCSS only at the root.
- **All colour/spacing/radius/shadow values come from `src/styles/tokens.css`.**
  Never hardcode a colour in `.scss`/`.css`/`.tsx`. For JS-side values (antd
  `ConfigProvider`, inline styles) import `tokens` from `src/styles/tokens.ts`.
- **SVG assets are the exception and must hardcode hex.** An SVG loaded through
  `<img src=…>` sits in its own document context and cannot read the host page's
  custom properties — `var(--accent)` there fails silently and renders black.
  Each asset carries a comment pointing back at `tokens.css`.
- Custom properties can't be used in `@media` conditions either; breakpoints stay
  literal (`768px`).
- The browser loads `public/favicon.svg`, not anything under `src/assets/`.

## Dependencies

### Internal
- `api/` → backend endpoints; `store/` → shared session/user state.

### External
- react-router-dom 6, antd 5, valtio 2, axios, ahooks, marked.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
