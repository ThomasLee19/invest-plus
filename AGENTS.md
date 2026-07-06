# AGENTS.md

Hard-earned context for agents working on **Invest+**. Read this before touching code.
For glossary and ubiquitous language, see [CONTEXT.md](CONTEXT.md). For agent-skill
setup (issue tracker, triage labels, domain docs), see [CLAUDE.md](CLAUDE.md) and
[docs/agents/](docs/agents/).

## Stack at a glance

A finance research agent: hand-rolled Plan → Act → Reflect → Answer pipeline
(no LangChain), three tools (`rag_search`, `finance_query`, `web_search`).
Backend [FastAPI](backend/app/app_main.py) + Postgres,
frontend [React + Vite](frontend/vite.config.ts), Elasticsearch 8.11 for hybrid
retrieval, DashScope (Alibaba) for LLM + embeddings.

## Directory map

Per-directory detail lives in nested `AGENTS.md` files:

- [backend/AGENTS.md](backend/AGENTS.md) — FastAPI app, run-from-`backend/app` rule
  - [backend/app/AGENTS.md](backend/app/AGENTS.md) — routers, models, schemas, db
    - [backend/app/service/AGENTS.md](backend/app/service/AGENTS.md) — agent pipeline + 3 tools
- [frontend/AGENTS.md](frontend/AGENTS.md) — React/Vite SPA
  - [frontend/src/AGENTS.md](frontend/src/AGENTS.md) — routes, components, stores, SSE
- [docs/AGENTS.md](docs/AGENTS.md) — agent conventions

## Running the system

There is **no Makefile, requirements.txt, pyproject.toml, or run-all script**.
Every component starts by hand. Order matters.

```bash
docker-compose up -d                      # ES on :1200 (mapped from 9200), PG on :5432
python scripts/index_finance.py           # one-time, populates ES index `finance_kb`
cd backend/app && uvicorn app_main:app --reload --port 8000   # NOT from backend/
cd frontend && npm install && npm run dev # Vite on :5181
```

- **Backend cwd is `backend/app`, not `backend/`.** Imports are flat
  (`from router import chat_rt`, `from utils.database`, `from schemas.chat`).
  Running from `backend/` produces `ModuleNotFoundError`. Exception:
  [`agent.py`](backend/app/service/agent/agent.py:24) inserts `backend/` into
  `sys.path` so it can do `from app.service.finance...`/`from app.database...`/
  `from app.utils...`. New backend code should follow the flat-import style,
  not the `app.*` style.
- **Python deps are undeclared.** Install from imports:
  `openai elasticsearch fastapi uvicorn sqlalchemy psycopg2-binary python-dotenv
  pydantic requests xxhash`. Scraping (Day-1 only) also needs `playwright` +
  `playwright install chromium`.
- **No `.env.example` Singapore endpoint.** The real `.env` uses a custom
  DashScope base URL different from the example; both work via OpenAI-compatible
  client.

## Elasticsearch quirks

- Port **1200** (host) → 9200 (container). All clients use `ES_URL=http://localhost:1200`.
- Auth is centralized in [es_client.py](backend/app/utils/es_client.py)'s
  `get_es_client()`, which reads `ES_URL`/`ELASTIC_PASSWORD` from the
  environment (same vars the docker container's `.env` already uses — no more
  duplicated hardcoded password). `agent.py`, `chat_rt.py` (all 3 call sites),
  and `file_parse.py` all construct their client through this one helper.
  `scripts/index_finance.py` is a standalone script with no `sys.path` hookup
  into `backend/app`, so it duplicates the same env-var-read pattern locally
  in its own `get_es()` instead of importing the shared helper.
- **One shared index `finance_kb`**, partitioned by `source_kwd`:
  - `source_kwd=sec_filing` / `news` / `educational` — finance corpus (loaded by `scripts/index_finance.py`).
  - `source_kwd=user_upload` — user-uploaded `.txt`/`.md` (loaded by [`file_parse.py`](backend/app/service/core/file_parse.py)).
  - **Real-time data is NOT in ES.** Quote/fundamentals/news-by-ticker come
    live from yfinance via
    [`finance_tool.py`](backend/app/service/finance/finance_tool.py); only the
    seed corpus + user uploads above are indexed.
- Hybrid retrieval (`rag_search`) sums BM25 + kNN. `_KNN_BOOST = 8.0`
  ([agent.py:131](backend/app/service/agent/agent.py:131)) balances BM25's score
  magnitude against cosine 0–1 — don't tune without understanding why. If query
  embedding fails it silently degrades to BM25-only.

## Agent pipeline — frozen contract

Names `agent_plan() → process_actions() → reflection() → final_answer()` are
fixed and **must not be renamed** ([CONTEXT.md "Agent Pipeline"](CONTEXT.md)).

- Two models: `qwen-plus` for plan/reflect (JSON output), `qwq-plus` for the
  streaming final answer (uses `delta.reasoning_content` for the visible thinking
  chain). Don't swap them.
- **Ticker extraction contract**: `finance_query` sub-questions must carry an
  explicit uppercase ticker (e.g. "AAPL price") — `agent_plan`'s prompt enforces
  this so `_TICKER_RE` (uppercase 1-5 letter words, minus stopwords like
  `I`/`US`/`CEO`) can reliably pull it out. Don't fall back to guessing a
  ticker from a lowercase company name.
- Language detection contract
  ([`_detect_language`](backend/app/service/agent/agent.py:779)): any CJK
  character → `zh`, else `en`. Japanese kana and Korean hangul are explicitly
  excluded. Used both for Serper `hl` and the final-answer system prompt.
- Conversation history is **last 5 turns** from the `messages` table, fetched in
  [chat_rt.py:47-54](backend/app/router/chat_rt.py:47).
- `USER_ID = "1"` is hard-coded in [chat_rt.py](backend/app/router/chat_rt.py:20)
  and [history_rt.py](backend/app/router/history_rt.py:9). There is no auth.
  Treat the system as single-user.

## Frontend

- Scripts: `dev | build | lint | preview | prepare`. **No `test`, no `format`**.
  Prettier auto-runs via Husky + lint-staged on staged files; ESLint and `tsc`
  are NOT in pre-commit — run `npm run lint` and `npm run build` manually
  before claiming a change is clean.
- Vite dev server proxies `/ai-search/*` → `http://localhost:8000/` **and strips
  the prefix** ([vite.config.ts:26](frontend/vite.config.ts:26)). The backend
  does NOT mount `/ai-search` — direct curl/prod calls must omit it.
- State: **Valtio** (not Redux/Zustand). Path alias: `@/` → `src/`.
- The mock plugin is intentionally disabled
  (`viteMockServe({ enable: !true })`). Don't re-enable casually.
- `package.json#name` is `shenweixueyuan` (template leftover, ignore — the
  product is Invest+).
- SSE event JSON shape consumed by
  [chat/index.tsx](frontend/src/pages/chat/index.tsx:155):
  `{role: 'agent'|'assistant', content, thinking?: bool}`. Frontend has dead
  branches for `documents`, `recommended_questions`, `image_results`,
  `video_results` — backend never emits these.

## Storage and persistence

- Upload directory resolves to **`<repo_root>/storage/file/<session_id>/`**
  via `../../../storage/file` from
  [chat_rt.py:15](backend/app/router/chat_rt.py:15). `backend/storage/file/`
  also exists in the tree but is **not written to** — likely a leftover.
- Postgres schema runs **once** via `docker-entrypoint-initdb.d/init.sql`
  ([init.sql](init.sql)). To pick up schema changes you must
  `docker-compose down -v` to drop the `investplus_pgdata` volume, or apply
  ALTERs by hand. Tables: `sessions`, `messages`, `knowledgebases`, `users`
  (the `users` table is unused).
- Chunk size is `MAX_CHUNK = 1500` chars in both ingestion paths — keep them in
  sync if you change one.
- Indexing is idempotent: `scripts/index_finance.py` keys chunk IDs by
  `xxhash(content + index)` and skips existing docs.

## Testing reality

- The only "test" is [`test_agent.py`](test_agent.py) — a single live smoke run
  that requires a working DashScope key, a populated ES, and Postgres. There is
  **no pytest suite, no fixtures, no CI**. Don't claim "tests pass" — there are
  none to pass.
- Backend has no mypy / ruff / black / formatter config. Frontend has ESLint +
  Prettier only.

## Files and dirs to treat carefully

- `.env` — gitignored, present locally, never the source of truth for what's
  deployed.
- `CONTEXT.md` is the **ubiquitous-language source of truth**. When naming
  things in code, issues, or PRs, use its terms (Ticker / Filing / RAG 知识库 /
  finance_query / rag_search / web_search / Query vs Advisory / Session /
  User Upload).

## CORS

`allow_origins=["*"]` is set without `allow_credentials`
([app_main.py:7-14](backend/app/app_main.py:7)). The two are incompatible under
the CORS spec — don't enable credentials without first narrowing origins.
