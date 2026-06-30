<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-01 | Updated: 2026-07-01 -->

# service

## Purpose
The brain of Invest+ (currently still running the pre-migration Pokemon tools
below — see root AGENTS.md migration note). Holds the **frozen** Plan → Act → Reflect → Answer agent
pipeline and the three tools it orchestrates: `rag_search` (Smogon KB via ES
hybrid retrieval), `pokeapi_query` (live PokeAPI structured facts), and
`web_search` (Serper fallback). Also hosts the upload→ES ingestion path.

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `agent/` | `agent.py` — the whole pipeline + tool dispatch + SSE generator |
| `pokeapi/` | `pokeapi_tool.py` — Gen 9 species & type-matchup queries against PokeAPI |
| `web_search/` | `web_search.py` — Serper search client + result post-processing |
| `core/` | `file_parse.py` — chunk → embed → bulk-index user uploads into ES |

### agent/agent.py — the contract
- Names `agent_plan() → process_actions() → reflection() → final_answer()` are
  inherited from the SalesPilot lineage and **must not be renamed**.
- Two models, do not swap: `qwen-plus` for plan/reflect (JSON mode), `qwq-plus`
  for the streaming final answer (uses `delta.reasoning_content` as the visible
  thinking chain).
- `final_answer()` is an **SSE generator**: emits "正在调用…" tool-status events,
  then streams assistant `content` / reasoning chunks, then `event: end [DONE]`
  (with a fallback emit if the stream ends without a finish_reason).
- `rag_search` is BM25 + kNN hybrid; `_KNN_BOOST = 8.0` balances BM25 score
  magnitude against cosine 0–1. If query embedding fails it **silently degrades
  to BM25-only**. Don't tune the boost without understanding the asymmetry.
- `_detect_language`: any CJK Han char → `zh`, else `en`; Japanese kana and
  Korean hangul are explicitly excluded first. Drives Serper `hl` and the
  final-answer system prompt.
- `pokeapi_tool()` routes "vs/对/克制/弱点/matchup" queries to type-matchup,
  otherwise resolves a species name via `resolve_pokemon_name()`.

### pokeapi/pokeapi_tool.py
- `GEN9_VERSION_GROUPS = {scarlet-violet, the-teal-mask, the-indigo-disk}` filters
  the learnset to Gen 9 only. (Same set is hard-coded in `legacy/fetch_pokemon_data.py`.)
- `resolve_pokemon_name()` probes hyphenated slugs **longest-to-shortest** so
  multi-word names (Iron Valiant, Great Tusk, Mr. Mime) resolve correctly — never
  naively `.split()[0]`.
- `query_pokemon` returns a formatted bilingual card; `query_type_matchup`
  computes a 0/0.25/0.5/1/2/4× multiplier from PokeAPI `damage_relations`.

### web_search/web_search.py
- `serper_search()` → `make_request()` POSTs to `google.serper.dev/search` with
  `SERPER_API_KEY`. `hl` is the region/language preference (zh-cn / en).
- `process_search_results()` extracts `{title, url, content}` snippets from
  `organic`. (`serper_images`/`serper_videos` exist but the agent only uses search.)

### core/file_parse.py
- `execute_insert_process`: split on blank lines into ≤ `MAX_CHUNK = 1500`-char
  chunks → embed with `text-embedding-v3` (1024-dim) → bulk-index into
  `pokemon_kb` with `source_kwd="user_upload"`, `refresh="wait_for"`.
- Keep `MAX_CHUNK = 1500` in sync with `legacy/index_smogon.py`.

## For AI Agents

### Working In This Directory
- ES auth is **hard-coded** `("elastic", "infini_rag_flow")` here and in three
  other call sites (see root AGENTS.md). Changing the password means touching all four.
- `agent.py` is the one file that imports siblings via `app.service.*` (it inserts
  `backend/` into `sys.path`). New code elsewhere uses flat imports.
- `pokeapi_query` and `rag_search` have **non-overlapping** jobs: exact
  numbers/structured facts vs. strategy/experience text. Don't blur them.

### Testing Requirements
No unit tests. Tools hit live external APIs (PokeAPI, Serper, DashScope, ES).
Exercise via the repo-root `test_agent.py` smoke run.

## Dependencies

### External
- openai (DashScope-compatible LLM + embeddings), elasticsearch 8.11,
  requests (PokeAPI), http.client (Serper).

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
