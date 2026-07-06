<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-01 | Updated: 2026-07-07 -->

# service

## Purpose
The brain of Invest+. Holds the **frozen** Plan → Act → Reflect → Answer agent
pipeline and the three tools it orchestrates: `rag_search` (finance knowledge
base — filings/news/educational docs — via ES hybrid retrieval), `finance_query`
(live quote/fundamentals/news via yfinance), and `web_search` (Serper fallback
for the latest market moves or gaps in the knowledge base).

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `agent/` | `agent.py` — the whole pipeline + tool dispatch + SSE generator |
| `finance/` | `finance_tool.py` — quote/fundamentals/news via yfinance |
| `web_search/` | `web_search.py` — Serper search client + result post-processing |
| `core/` | `file_parse.py` — chunk → embed → bulk-index user uploads into ES |

### agent/agent.py — the contract
- Names `agent_plan() → process_actions() → reflection() → final_answer()` are
  fixed and **must not be renamed**.
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
- `finance_tool()` extracts an uppercase 1-5 letter ticker from the query
  (`_TICKER_RE`, minus common-word stopwords like `I`/`US`/`CEO`) and routes to
  `query_quote` / `query_fundamentals` / `query_news` based on keyword matches
  (`_NEWS_KEYWORDS`, `_FUNDAMENTALS_KEYWORDS`); defaults to quote.

### finance/finance_tool.py
- `query_quote` / `query_fundamentals` / `query_news` all funnel through
  `_load_ticker()`, which caches one `yf.Ticker` + `.info` + `.history` fetch
  per ticker per process to avoid duplicate requests across the three modes.
- `_is_valid_ticker()` treats a ticker as valid if it has non-empty history OR
  a substantive `.info` field (`symbol`/`regularMarketPrice`) — yfinance
  doesn't raise on an invalid ticker, it just returns near-empty data.

### web_search/web_search.py
- `serper_search()` → `make_request()` POSTs to `google.serper.dev/search` with
  `SERPER_API_KEY`. `hl` is the region/language preference (zh-cn / en).
- `process_search_results()` extracts `{title, url, content}` snippets from
  `organic`.

### core/file_parse.py
- `execute_insert_process`: split on blank lines into ≤ `MAX_CHUNK = 1500`-char
  chunks → embed with `text-embedding-v3` (1024-dim) → bulk-index into
  `finance_kb` with `source_kwd="user_upload"`, `refresh="wait_for"`.
- Keep `MAX_CHUNK = 1500` in sync with `scripts/index_finance.py`.

## For AI Agents

### Working In This Directory
- ES auth goes through the shared `get_es_client()` helper in
  `backend/app/utils/es_client.py` (reads `ELASTIC_PASSWORD`/`ES_URL` from
  env — see root AGENTS.md). Don't reintroduce an inline `Elasticsearch(...)`
  construction with hardcoded credentials in new code.
- `agent.py` is the one file that imports siblings via `app.service.*` (it inserts
  `backend/` into `sys.path`). New code elsewhere uses flat imports.
- `finance_query` and `rag_search` have **non-overlapping** jobs: exact
  real-time numbers/structured facts vs. filing/news/educational narrative
  text. Don't blur them.

### Testing Requirements
No unit tests here (see `backend/tests/test_agent_loop.py` for the pure-logic
suite one level up). Tools hit live external APIs (yfinance, Serper,
DashScope, ES). Exercise via the repo-root `test_agent.py` smoke run.

## Dependencies

### External
- openai (DashScope-compatible LLM + embeddings), elasticsearch 8.11,
  yfinance (finance_query), http.client (Serper).

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
