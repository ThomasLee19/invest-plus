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
| `components/` | Reusable UI: `header-bar`, `home-banner`, `hot-questions`, `markdown`, `page-layout`, `sender`, `icons` |
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
  The frontend has **dead branches** for `documents`, `recommended_questions`,
  `image_results`, `video_results` — the backend never emits these. Don't build
  on them without a backend change.
- Use the `@/` alias for imports (→ `src/`). State lives in Valtio stores under
  `store/`; don't reach for React Context for shared state.
- API calls go through `api/` (axios instance + plugin chain in `api/request/`),
  not raw `fetch`, except the SSE stream which is handled in `utils/useSendMessage`.

### Testing Requirements
No unit tests. Validate with `npm run lint` and `npm run build` from `frontend/`,
then exercise the page in `npm run dev`.

### Common Patterns
- Component-per-folder with co-located `index.tsx` + `index.module.scss`.
- CSS Modules (`*.module.scss`) for component styles; global SCSS only at the root.

## Dependencies

### Internal
- `api/` → backend endpoints; `store/` → shared session/user state.

### External
- react-router-dom 6, antd 5, valtio 2, axios, ahooks, marked.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
