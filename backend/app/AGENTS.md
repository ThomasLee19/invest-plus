<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-01 | Updated: 2026-07-01 (post finance-migration Phase 1-3 pass) -->

# app

## Purpose
The FastAPI application root. `app_main.py` wires CORS and mounts the two
routers; everything else is split into routers (HTTP surface), services (agent
+ tools), and thin data layers (models / schemas / database / utils). cwd for
running uvicorn is **this directory**.

## Key Files
| File | Description |
|------|-------------|
| `app_main.py` | FastAPI app; `allow_origins=["*"]` **without** `allow_credentials` (intentional — the two are incompatible per CORS spec). Mounts `chat_rt` + `history_rt`. |
| `__init__.py` | Package marker (enables the `app.*` import path used only by `service/agent/agent.py`). |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `router/` | HTTP endpoints (chat/SSE, file upload, session & message history) |
| `service/` | Agent pipeline + the three tools, finance domain (`rag_search`, `finance_query`, `web_search` — see `service/AGENTS.md`) |
| `models/` | SQLAlchemy declarative models (`Session`, `Message`) |
| `schemas/` | Pydantic request bodies (`ChatRequest`) |
| `database/` | Knowledgebase table helpers (raw SQL) |
| `utils/` | DB engine/session factory + `get_db` dependency |

### router/
- `chat_rt.py` — `POST /create_session`, `POST /chat` (SSE streaming + writes the
  collected answer/think back to `messages`), `POST /upload_files/`,
  `GET /get_files/`, `DELETE /delete_file/`. History = **last 5 turns**.
  `STORAGE_DIR` resolves to `<repo_root>/storage/file` via `../../../storage/file`.
- `history_rt.py` — `GET/DELETE /sessions`, `GET /messages`. Lists by `USER_ID="1"`.

### models/
- `message.py` — `Base`, `Session` (16-char id), `Message` (uuid pk, `think` column
  holds the reasoning chain). Models exist but routers use raw `text()` SQL, not the ORM.

### schemas/
- `chat.py` — `ChatRequest { message: str }`. The only request schema.

### database/
- `knowledgebase_operations.py` — `insert_knowledgebase` / `delete_knowledgebase_entry`
  / `get_latest_user_upload` on the `knowledgebases` table.

### utils/
- `database.py` — reads `DATABASE_URL`, builds the engine + `SessionLocal`, exposes
  `get_db()` (FastAPI dependency) and `init_db()` (unused; schema comes from `init.sql`).

## For AI Agents

### Working In This Directory
- Endpoints are **not** under a `/ai-search` prefix. The Vite dev proxy adds and
  strips that prefix; direct curl / prod calls must omit it.
- The `/chat` SSE generator both yields events **and** accumulates `content`
  (thinking=False) and reasoning (thinking=True) to persist after the stream ends.
  Keep that dual responsibility intact if you touch it.
- Session id = first 16 hex chars of a uuid4. `session_name` is auto-set to the
  first question's first 20 chars on the first message.

### Common Patterns
- All persistence is raw SQL via `db.execute(text(...), params)` + explicit
  `commit()` / `rollback()`. Match this; don't introduce ORM query style.

### Testing Requirements
See [`backend/AGENTS.md`](../AGENTS.md#testing-requirements) — there is now a
unit suite at `backend/tests/test_agent_loop.py` (11 tests, zero external
deps/network, run via `python -m unittest tests.test_agent_loop` from `backend/`).

## Dependencies

### Internal
- `service.agent.agent.final_answer` — the SSE generator driving `/chat`.
- `service.core.file_parse.execute_insert_process` — upload → ES ingestion.

### External
- fastapi, sqlalchemy, pydantic.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
