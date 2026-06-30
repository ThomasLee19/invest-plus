<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-01 | Updated: 2026-07-01 -->

# backend

## Purpose
FastAPI backend for PokemonRA — a Gen 9 competitive Pokémon Q&A agent. Hosts the
hand-rolled Plan → Act → Reflect → Answer pipeline (no LangChain), the HTTP/SSE
API, Postgres persistence, and Elasticsearch hybrid retrieval. Read the root
[AGENTS.md](../AGENTS.md) first — it holds the hard-earned operational warnings
(ES auth, import style, frozen pipeline contract) that this file does not repeat.

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
- Python deps are **undeclared** (no requirements.txt / pyproject.toml). Install
  from imports: `openai elasticsearch fastapi uvicorn sqlalchemy psycopg2-binary
  python-dotenv pydantic requests xxhash`.
- New code should follow the **flat-import** style, not `app.*`. The only file
  that uses `app.*` is `app/service/agent/agent.py`, which deliberately inserts
  `backend/` into `sys.path` to reach sibling tool modules.

### Testing Requirements
There is **no pytest suite, no CI**. The only check is the repo-root
`test_agent.py` live smoke run, which needs a real DashScope key, populated ES,
and running Postgres. Don't claim "tests pass" — there are none.

### Common Patterns
- Raw SQL via SQLAlchemy `text()` with bound params (no ORM queries despite the
  declarative models existing).
- `USER_ID = "1"` hard-coded everywhere. The system is single-user, no auth.

## Dependencies

### Internal
- Postgres schema is created once from repo-root `init.sql` via docker-compose.
- Elasticsearch index `pokemon_kb` (shared, partitioned by `source_kwd`).

### External
- FastAPI + uvicorn (HTTP/SSE), SQLAlchemy + psycopg2 (Postgres),
  elasticsearch 8.11 client, openai client (DashScope-compatible), requests (PokeAPI).

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
