<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-01 | Updated: 2026-07-01 -->

# backend

## Purpose
FastAPI backend for **Invest+**, a finance research agent (migrated from
PokemonRA, a Gen 9 Pokémon Q&A prototype — the migration reused this backend's
architecture wholesale). Hosts the hand-rolled Plan → Act → Reflect → Answer
pipeline (no LangChain; Phase 1 of the migration replaced the single hardcoded
reflection pass with a genuinely LLM-driven bounded loop — see
`should_continue()` in `agent.py`), the HTTP/SSE API, Postgres persistence, and
Elasticsearch hybrid retrieval over the `finance_kb` index (filings/news/
educational/user uploads). Read the root [AGENTS.md](../AGENTS.md) first — it
holds the hard-earned operational warnings (ES auth, import style, frozen
pipeline contract) that this file does not repeat.

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `app/` | All application code: routers, services, models, schemas (see `app/AGENTS.md`) |
| `storage/file/` | Leftover upload dir — **not written to**. Real uploads land in `<repo_root>/storage/file/`. Ignore. |

## For AI Agents

### Working In This Directory
- **Run uvicorn from `backend/app`, NOT from `backend/`.** Imports are flat
  (`from router import chat_rt`). Starting from `backend/` gives `ModuleNotFoundError`.
  ```bash
  cd backend/app && uvicorn app_main:app --reload --port 8000
  ```
- Python deps are declared in repo-root `requirements.txt` (covers `backend/`
  and `scripts/`, including the DeepDoc PDF pipeline's onnxruntime/torch/xgboost
  stack). Install with `pip install -r requirements.txt` from the repo root.
- New code should follow the **flat-import** style, not `app.*`. The only file
  that uses `app.*` is `app/service/agent/agent.py`, which deliberately inserts
  `backend/` into `sys.path` to reach sibling tool modules.

### Testing Requirements
There is **no CI**, but there is now a real unit test suite:
[`tests/test_agent_loop.py`](tests/test_agent_loop.py) — 11 tests covering
`should_continue()`'s decision logic, the bounded reflection while-loop in
`final_answer()`, and tool-error propagation into `memory`. Run from `backend/`:
```bash
python -m unittest tests.test_agent_loop -v
```
It runs with **zero installed third-party packages and zero network access**
by stubbing `openai`, `dotenv`, and `app.service.pokeapi.pokeapi_tool` via
`sys.modules` before importing `agent.py`; the actual LLM call boundary
(`_llm_json`) is mocked per-test. `pytest` is not currently installed in the
dev env, but the suite is plain-`unittest`-based so `pytest` would also work.
Separately, [`test_agent.py`](../test_agent.py) at the repo root is still a
live, full-stack smoke run (real DashScope key, populated ES, running
Postgres) — it complements but doesn't replace the unit suite.

### Common Patterns
- Raw SQL via SQLAlchemy `text()` with bound params (no ORM queries despite the
  declarative models existing).
- `USER_ID = "1"` hard-coded everywhere. The system is single-user, no auth.

## Dependencies

### Internal
- Postgres schema is created once from repo-root `init.sql` via docker-compose.
- Elasticsearch index `finance_kb` (renamed from `pokemon_kb` in the finance
  migration — see
  [`.omc/plans/finance-agent-migration-plan.md`](../.omc/plans/finance-agent-migration-plan.md)),
  shared, partitioned by `source_kwd` (`sec_filing` / `news` / `educational` /
  `user_upload`).

### External
- FastAPI + uvicorn (HTTP/SSE), SQLAlchemy + psycopg2 (Postgres),
  elasticsearch 8.11 client, openai client (DashScope-compatible), yfinance
  (`service/finance/finance_tool.py` — replaced the PokeAPI dependency),
  onnxruntime/torch/xgboost/opencv (DeepDoc PDF parsing pipeline ported from
  FinReportRAG for filing uploads, `service/core/deepdoc` + `service/core/rag`).
  Full pinned list: repo-root [`requirements.txt`](../requirements.txt).

### Known dead code
- `app/service/pokeapi/` (the old `pokeapi_tool.py`) is no longer imported by
  anything — `agent.py` now dispatches to `app/service/finance/finance_tool.py`
  instead. Left on disk, not wired in; safe to delete.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
