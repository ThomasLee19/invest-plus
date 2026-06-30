<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-01 | Updated: 2026-07-01 -->

# frontend

## Purpose
React 18 + Vite + TypeScript SPA for Invest+ — chat UI with streaming answers,
a thinking-chain view, session history, and a document repository (upload/manage
the user knowledge base). Talks to the FastAPI backend over SSE. UI copy
(banner title, example questions) still reflects the pre-migration Pokemon
domain — that's Phase 4 of the migration, not yet done; see root AGENTS.md.

## Key Files
| File | Description |
|------|-------------|
| `vite.config.ts` | Dev server on **:5181**; proxies `/ai-search/*` → `http://localhost:8000/` and **strips** the prefix. Mock plugin intentionally disabled (`enable: !true`). |
| `package.json` | `name` is `shenweixueyuan` (template leftover — ignore). Scripts: `dev / build / lint / preview / prepare`. **No `test`, no `format`.** |
| `index.html` | SPA entry. |
| `eslint.config.js` | Flat ESLint config (TS + react-hooks + react-refresh). |
| `tsconfig*.json` | App/node split TS configs; `@/` path alias → `src/`. |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `src/` | Application source (see `src/AGENTS.md`) |
| `public/` | Static assets served as-is (incl. `pricing/`) |
| `mock/` | mockjs fixtures for the (disabled) vite-plugin-mock |

## For AI Agents

### Working In This Directory
- **No automated tests.** Prettier auto-runs via Husky + lint-staged on staged
  files, but ESLint and `tsc` are **not** in pre-commit. Before claiming a change
  is clean, run `npm run lint` and `npm run build` manually.
- The `/ai-search` prefix only exists in dev via the proxy. Don't bake it into
  code that might run against prod.
- State is **Valtio** (not Redux/Zustand). UI library is **antd 5**. Markdown is
  rendered with `marked`.

### Testing Requirements
```bash
npm install
npm run lint     # ESLint
npm run build    # tsc -b && vite build  (the real type check)
npm run dev      # Vite on :5181
```

## Dependencies

### Internal
- Backend SSE `/chat` endpoint (proxied through `/ai-search`).

### External
- react 18, react-router-dom 6, antd 5, valtio 2, axios, ahooks, marked,
  dayjs, lodash-es. Build: vite 6, typescript 5.7, vite-plugin-svgr.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
