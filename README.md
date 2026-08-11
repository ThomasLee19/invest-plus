[English](README.md) | [简体中文](README.zh-cn.md)

# Invest+ — AI Finance Research Assistant

Invest+ is an autonomous research agent for US equities. Ask it about a stock
in plain English or Chinese, and it plans its own research, pulls live
market data, searches SEC filings and news, and streams back a sourced
answer — deciding for itself which tools to use and when it has enough
information to stop.

## Live Demo

**[https://investplus-agent.com](https://investplus-agent.com)**

Hosted on a single Docker Compose stack (Elasticsearch + PostgreSQL + backend
+ frontend, behind an nginx gateway with Let's Encrypt TLS) on a non-mainland
-China cloud node, deployed via GitHub Actions CI/CD on every push to
`master`. Rate-limited (20 req/min) as light friction against casual/
automated traffic, not as a real access-control layer — see
[Production Deployment](#production-deployment).

## Features

- **Autonomous agent loop** — a single decision operation iterating over an
  append-only trajectory. The agent decides which tools to call, breaks
  questions into sub-queries, and keeps gathering until it judges the answer
  complete (bounded by a safety cap so it can't loop forever — if the cap is
  hit before the model signals completion, the final answer discloses that
  information may be incomplete rather than presenting a partial result as
  exhaustive). No hardcoded decision tree — every continue/stop/retry choice
  comes from the model's own native `tool_calls` output.
- **Three research tools**:
  - `rag_search` — a hybrid (BM25 + vector) search over a knowledge base of
    SEC filings (10-K/10-Q/8-K), news, and educational reference articles
  - `finance_query` — live market data via yfinance (quote, fundamentals,
    recent news)
  - `web_search` — general web search for the latest market moves or gaps
    in the knowledge base
- **Streaming, visible reasoning** — SSE streaming with the agent's live
  thinking/reasoning chain shown alongside the final answer, not just the
  end result.
- **Bilingual** — auto-detects Chinese or English input and responds in
  kind; UI has a 中/EN toggle.
- **Multi-turn conversations** — session-scoped chat history.
- **File uploads** — upload your own `.txt` / `.md` / `.pdf` filings (PDFs
  parsed with a table-aware layout/OCR pipeline); manage them from the Docs
  page.
- **Cross-lingual retrieval that actually works** — the hybrid BM25+vector
  search recovers relevant results for conversational-language queries that
  keyword search alone misses entirely (see [How It Works](#how-it-works)).
- **Cross-session memory** — the agent remembers who you are across
  conversations, not just within one: a user profile (risk preference,
  investment style, watched tickers) and a tiered-TTL research-conclusion
  store (fundamentals/filing facts ~90 days, news ~30 days; real-time quotes
  are never persisted as "memory" — they're recalled live every time). Both
  are recalled on every request and actually reach the answer, not just the
  planning step (see [How It Works](#how-it-works)).
- **LLM memory extraction** — every 5 turns, a background pass (no request
  latency added) reads the recent conversation and extracts structured
  facts, with deterministic schema validation and untrusted-content fencing
  standing between whatever the extraction LLM outputs and what actually
  gets persisted.
- **Skill SOP library** — four research playbooks (valuation, financial
  statement, industry comparison, risk scan). Their metadata catalogue sits in
  the static system prefix, and the model pulls a playbook's full body via a
  `load_sop` tool call when it judges one applies, rather than a separate
  classification round-trip loading it up front. How much this changes the
  sub-questions actually asked is currently **unquantified** — see the SOP note
  under [Quantitative Evaluation](#quantitative-evaluation).
- **Disclaimer, guaranteed** — every answer ends with a fixed disclaimer
  appended by code after generation, not requested via prompt instruction,
  so it can't be dropped by the model.

## Quick Start

### Prerequisites
- Docker Desktop (with WSL integration enabled, if on WSL2)
- Python 3.11+ (a conda env is recommended)
- Node.js 18+
- A DashScope API key (Alibaba Cloud) and a Serper API key

### 1. Set up environment variables
Copy `.env.example` to `.env` and fill in your keys:
```env
DASHSCOPE_API_KEY=your_dashscope_key
DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
SERPER_API_KEY=your_serper_key
ES_URL=http://localhost:1200
ELASTIC_PASSWORD=your_elastic_password
TIMEZONE=Asia/Shanghai
MEM_LIMIT=4294967296
PG_MEM_LIMIT=1073741824
POSTGRES_PASSWORD=your_postgres_password
DATABASE_URL=postgresql://postgres:your_postgres_password@localhost:5432/investplus
```

### 2. Start infrastructure
```bash
docker compose up -d
```

### 3. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 4. Fetch and index the finance corpus
```bash
python scripts/fetch_filings.py       # SEC EDGAR filings (10-K/10-Q/8-K) -> data/filings/
python scripts/fetch_news.py          # recent news per ticker -> data/news/
python scripts/fetch_educational.py   # curated reference articles -> data/educational/
python scripts/index_finance.py       # chunk + embed + index all three into ES `finance_kb`
```

### 5. Start the backend
```bash
cd backend/app
uvicorn app_main:app --reload --port 8000
```

### 6. Start the frontend
Copy `frontend/.env.example` to `frontend/.env`:
```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open [http://localhost:5181](http://localhost:5181).

## Production Deployment

The [live demo](#live-demo) runs from the same repo via a second Compose
file layered on top of the dev one:

- `docker-compose.prod.yml` — adds `backend`/`frontend`/`gateway` services
  (built from `backend/Dockerfile`, `frontend/Dockerfile`, `gateway/Dockerfile`),
  pins a `mem_limit` per service (calibrated against measured container
  memory under real load, not guessed), and drops the dev-only host port
  publishing for `es01`/`pg`.
- `gateway/` — a single nginx container is the only public entry point:
  TLS (Let's Encrypt via `certbot`, two-stage bootstrap to break the
  chicken-and-egg cert/nginx startup order), `/ai-search/*` reverse-proxied
  to the backend with SSE passthrough (buffering off), and request rate
  limiting.
- `.github/workflows/deploy.yml` — on push to `master`: builds and pushes
  `backend`/`frontend`/`gateway` images to GHCR, then SSHes into the server
  to `pull` + `up -d`. The deploy SSH key only ever runs those two commands;
  business secrets (`.env`) are placed on the server by hand once, never
  transmitted through CI.

Not a generic "deploy anywhere" template — the compose files and gateway
config are written against this project's specific service layout, and the
mem_limit values are calibrated for one particular VM size. Treat them as a
worked example, not a drop-in.

## How It Works

```
User question
      ↓
  static prefix        ── system prompt + tool definitions + SOP metadata catalogue;
      ↓                    byte-stable across requests, so it is cacheable
  decision operation   ── LOOPS: one LLM call answering both "keep gathering?" and
      ↓  (bounded loop)    "which tool, which arguments", emitted as native tool_calls
  process_actions()    ── calls rag_search / finance_query / web_search / load_sop;
      ↓                    tool errors are surfaced to the LLM, not swallowed
      ↓                  results append to the trajectory as tool-role messages
      ↓                    paired with their tool_call_id; the list only grows
  final_answer()       ── separate call on a stronger model; streams via SSE
      ↓
  Frontend renders thinking chain + final answer
```

The loop exits on any of three conditions: the model issues no further tool
calls, the round cap is hit, or a call errors out. `final_answer()`
deliberately sits off the trajectory — it buys a better-quality answer at the
cost of an extra round trip and a model that shares no cache with the loop.

**Tool selection rules:**
- Real-time quote / market cap / P/E ratio / fundamentals / news headlines → `finance_query`
- Filing content / risk factors / news analysis / concept explanations → `rag_search`
- Latest market-wide events not covered by the knowledge base → `web_search`
- Off-topic (non-finance) questions → rejected

**Why the loop is a genuine agent loop, not a scripted pipeline:** every
continue/stop/retry decision comes from the model's own native `tool_calls`
output, not from hardcoded branching — a round with no tool calls *is* the
stop signal. A safety cap (5 iterations) bounds runaway loops without being
mistaken for genuine LLM judgment; cap-stops are logged distinctly from
model-signaled stops. Tool failures are appended to the trajectory the model
itself reads, so it can retry, fall back, or flag an incomplete answer
instead of the backend silently swallowing the failure.

This shape is the result of a rewrite, not the original design. The first
version put tool descriptions in the prompt body, had the model emit JSON
text that the backend parsed, and re-serialized accumulated tool results into
a fresh user message each round. That last part is the failure mode the
current design exists to avoid: the model never saw its own call history, only
text reformatted by the application, so it re-issued calls it had already
made. Two layers of deduplication were added to suppress the symptom, and
both were deleted once the trajectory was made real. Measured on five
questions deep enough to need multiple rounds: at comparable follow-up depth,
repeat attempts went from 3 to 0, total tool calls from 77 to 34, and average
wall time from 108.7s to 75.3s.

**Cross-lingual hybrid retrieval:** `rag_search` combines two signals over
the same Elasticsearch index (native ES 8.11 `knn` + `query`, hand-rolled —
no RAGFlow dependency):
- **BM25** (`content_ltks` full-text) — precise keyword matches.
- **Vector kNN** (`q_1024_vec`, text-embedding-v3, cosine) — semantic and
  cross-lingual matches.

Scores from both branches are summed (vector branch boosted to balance
magnitudes); if query embedding fails, it degrades gracefully to BM25-only.
Combined candidates are then reranked with qwen3-vl-rerank before an
upload-recency boost narrows the final set to the top 5.
This mechanism is validated directly against the `finance_kb` corpus by
[`eval/recall_validation.py`](eval/recall_validation.py), which calls the
same query-construction code `rag_search` uses in production: across 10
Chinese conversational finance questions against this project's
English-only corpus (SEC filings, news, educational docs), BM25-only
recall was **0%** (0/10), while hybrid (BM25 + vector) recall was **100%**
(10/10) — see the script for the exact queries and hit counts.

**Cross-session memory:** before entering the decision loop, `final_answer()`
recalls the user's profile (`recall_user_profile`, `service/memory/profile.py`)
and, by extracting tickers from the raw question with a CJK-tolerant regex
(`_extract_tickers_loose`, `agent.py:416`) that catches tickers glued to
Chinese text (`_TICKER_RE`'s `\b` word boundaries miss e.g. "AAPL的股价"),
any relevant unexpired research conclusions
(`recall_all_conclusions`, `agent.py:429`). Both are woven into the planning
prompt (so the agent can skip redundant fetches), and the same recalled
conclusions are **also** spliced into the final answer prompt — a fact
recalled from a prior session can actually show up in this turn's answer,
not just influence which tools get called. Recalled content is wrapped in
`<untrusted_context>` with an explicit "treat live data as authoritative if
they conflict" instruction, same convention as tool results.

Every 5 turns, a `BackgroundTasks`-scheduled pass
(`service/memory/extraction.py`) reads the recent conversation and asks the
LLM to extract structured facts (updated preferences, timestamped
conclusions). Real-time quote data is dropped by code before it ever reaches
validation — it has no business being cached as long-term "memory." What
survives is schema-validated deterministically (enums, ticker/metric-name
regexes, length caps) before being written, so a successful prompt
injection against the extraction LLM can produce confusing *content* but
can't write an out-of-schema value or escape the sandboxed prompt string.

**Skill SOP library:** four playbooks live as plain Markdown files under
`service/agent/skills/` (`valuation.md`, `financial_statement.md`,
`industry_comparison.md`, `risk_scan.md`), each with YAML frontmatter and an
indicator checklist. Only their `name` + `description` pairs are resident,
appended to the decision system prompt as a metadata catalogue; the bodies
enter context solely when the model calls the `load_sop` tool, which returns
the body as a tool message. Measured cost of that split: 813 characters
resident against 3082 characters of bodies, so 26%.

This replaced an independent `classify_skill()` round-trip that ran
unconditionally before planning. The saving is not on questions that need a
playbook — those break even, one classification call becoming one `load_sop`
call — it is that questions needing no playbook stop paying at all. Stated
honestly, the switch cost some routing recall: positives fell 19/19 → 16/19
while false positives held at 0/16, and only one of those three is a clean
regression (one is a self-contradicting dataset label, and one is a scoring
mismatch, since the old call hard-capped its output at two skills and
`load_sop` has no such cap). Timing is unresolved: the path structurally
loses a whole LLM round trip, but the measurements disagree with each other
inside the sampling noise, so no claim is made either way.

SOP bodies deliberately never enter the memory channel — they are
instructions to the model, not facts about the world, and letting them in
would feed the user's own methodology checklist back to them as cited
reference material. A test pins that.

## Tech Stack

| Layer | Technology | Role |
|---|---|---|
| LLM | Qwen — qwen3.7-max (final answer), qwen-plus (decision operation), via the `openai` SDK against DashScope's OpenAI-compatible endpoint | Reasoning + tool decisions |
| Agent Framework | Hand-rolled loop: static prefix + append-only trajectory + native tool calling (no LangChain) | Tool orchestration + self-correction |
| Knowledge Base | Elasticsearch `finance_kb` (SEC filings + news + educational + user uploads); text-embedding-v3 for vector embeddings, qwen3-vl-rerank (native `dashscope` SDK) for reranking | Hybrid retrieval (BM25 + vector) + rerank |
| Real-time Data | yfinance (`service/finance/finance_tool.py`) | Quote / fundamentals / news |
| Document Parsing | DeepDoc (layout/table-transformer/OCR, onnxruntime) | PDF filing uploads → table-aware chunks |
| Web Search | Serper API | Latest market moves / fallback |
| Backend | FastAPI + PostgreSQL | API, SSE, sessions & messages; `user_profiles`/`conclusion_memory` for cross-session memory |
| Memory & Skills | `service/memory/{profile,conclusion,extraction}.py`, `service/agent/skills/*.md` | Cross-session recall, LLM extraction pipeline, SOP-driven planning |
| Frontend | React + TypeScript + Vite + Ant Design + Valtio | Chat UI, streaming render, doc mgmt |
| Infrastructure | Docker Compose (ES + PG for local dev; full stack + nginx gateway + Let's Encrypt for prod) | Local dependencies / production hosting |
| CI/CD | GitHub Actions + GHCR | Build/push images on every push; SSH deploy (`pull` + `up -d`) on `master` |

## Project Structure

```
InvestPlus/
├── backend/
│   ├── Dockerfile                   # Prod image: deps → tiktoken/nltk pre-bake → app code (in that layer order, for cache hits on code-only changes)
│   └── app/
│       ├── app_main.py              # FastAPI entry point
│       ├── router/
│       │   ├── chat_rt.py           # /chat SSE, /upload_files (.txt/.md/.pdf), /get_files, /delete_file
│       │   └── history_rt.py        # /sessions, /messages
│       ├── service/
│       │   ├── agent/
│       │   │   ├── agent.py         # Agent loop (decision operation over a trajectory) + memory/skill recall & injection
│       │   │   └── skills/          # SOP playbooks: valuation/financial_statement/industry_comparison/risk_scan.md
│       │   ├── memory/
│       │   │   ├── profile.py       # recall_user_profile / upsert_user_profile
│       │   │   ├── conclusion.py    # recall_conclusion_facts / upsert_conclusion_fact (tiered TTL)
│       │   │   └── extraction.py    # extract_memory() — every-5-turn LLM extraction pipeline
│       │   ├── finance/              # finance_tool.py — live yfinance quote/fundamentals/news
│       │   ├── web_search/          # Serper web search tool
│       │   └── core/
│       │       ├── file_parse.py    # .txt/.md chunker + .pdf DeepDoc pipeline -> ES indexer
│       │       ├── deepdoc/         # PDF parser (layout/table/OCR)
│       │       └── rag/             # Tokenizer/nlp utils + res/deepdoc model weights
│       ├── models/memory.py         # SQLAlchemy models: UserProfile, ConclusionMemory
│       ├── schemas/chat.py
│       └── utils/database.py
│   └── tests/
│       ├── test_agent_loop.py       # Loop-mechanism unit tests (should_continue, error propagation) + merge-step tests
│       ├── test_chat_router.py      # /chat SSE + related router endpoints
│       ├── test_history_router.py   # /sessions, /messages
│       ├── test_finance_tool.py     # yfinance wrapper, degrade-on-failure, ticker cache
│       ├── test_file_parse.py       # .txt/.md/.pdf chunking + ES indexing
│       ├── test_pdf_parser.py       # DeepDoc PDF parser
│       ├── test_es_client.py        # Elasticsearch client singleton/config
│       ├── test_knowledgebase_operations.py
│       ├── test_index_finance.py    # Bulk corpus indexer
│       ├── test_e2e_finance.py      # Live end-to-end smoke test against a running backend
│       ├── test_memory_layer.py     # Profile/conclusion read-write + extraction validation
│       ├── test_memory_recall.py    # CJK-tolerant ticker extraction + recall wiring
│       ├── test_memory_scheduling.py # Discriminative BackgroundTasks trigger tests
│       └── test_skill_sop_and_disclaimer.py
├── eval/                             # Quantitative agent/RAG evaluation harness (see below)
├── frontend/
│   ├── Dockerfile                   # Multi-stage: npm build -> static assets served by nginx
│   └── src/
│       ├── i18n.tsx                 # Bilingual text (zh/en)
│       ├── components/
│       │   ├── header-bar/          # Header with 中/EN toggle
│       │   └── sender/              # Input box + file attachment
│       └── pages/
│           ├── chat/                # Chat page with SSE streaming
│           └── repository/          # Document management
├── gateway/                          # Prod entry point: nginx TLS/reverse-proxy/rate-limit/Basic Auth
│   ├── Dockerfile
│   ├── nginx.conf                   # Production config (TLS, real domain)
│   └── nginx.local.conf             # Local-stack equivalent (plain HTTP, no certbot)
├── .github/workflows/deploy.yml     # CI: build all 3 images on every push; on master, also push to GHCR + SSH deploy
├── scripts/                          # Finance corpus fetch/index scripts (fetch_filings/news/educational, index_finance)
├── data/                             # Fetched finance corpus (filings/news/educational), indexed into `finance_kb`
├── docker-compose.yml                # ES + PostgreSQL (shared base)
├── docker-compose.local.yml          # + backend/frontend/gateway for local full-stack dev (plain HTTP)
├── docker-compose.prod.yml           # + backend/frontend/gateway/certbot for production (TLS, mem_limit pins)
└── .env                              # API keys and config
```

## Quantitative Evaluation

A reproducible evaluation harness (`eval/`) drives the live backend
end-to-end (real agent/RAG/Elasticsearch logic, no mocks) against a labeled
dataset built from the actual indexed corpus:

| Metric | Result | Basis |
|---|---|---|
| Tool-routing average hit rate | **74.5%** | 17 questions × **3 samples each**. 10 stable hits, 3 stable failures, **4 questions that flip** (right on one run and wrong on the next, on identical code) |
| First substantive judgement latency | **2.93s avg** (p50 2.63s / p90 4.86s) | `POST /chat` to the first tool-call event. This is the number that measures responsiveness |
| Full response latency | 32.6s avg (p50 31.9s / p90 55.0s) | 32 real streaming requests, start to end of the streamed answer |
| RAG retrieval/answer accuracy | 13/15 | fact-based QA pairs checked against the actual filings/news/educational corpus |
| Edge-case robustness | 5/5 | empty input, oversized input, invalid ticker, off-topic question, non-existent session |

**The numbers below are not citable. The reasons are recorded here rather than
quietly dropped:**

- **"Time to first token" / "first-feedback latency"** — since [`448b831`](.),
  the first SSE event is an acknowledgment the backend emits *before* any LLM
  call, and it measures a constant 0.00s. It proves the connection is open; it
  measures nothing about the model, retrieval, or tools. For responsiveness,
  quote "first substantive judgement" from the table above.
- **Single-sample strict routing accuracy** — 4 of the 17 questions flip on
  identical code, which puts roughly **±24 percentage points** of swing on any
  single-sample figure. Any before/after comparison smaller than that band is
  unreadable, so this README reports only the multi-sample average hit rate.
- **SOP injection coverage lift** — both rulers are known broken. The old one
  counted keywords in the generated sub-questions, but `finance_tool` does not
  parse specific metrics: `"AAPL PE ratio"` and `"AAPL fundamentals"` return
  byte-identical results, so it was rewarding verbosity rather than
  information. Rescoring the same data on what the tools actually returned
  dropped the lift from +52.8pp to +11.1pp — but the new ruler saturates too
  (the fundamentals card always carries exactly 2 of the 5 valuation concepts,
  giving the score two settings). Redesigning the scoring dimensions is
  outstanding work.

**Where the latency actually goes** is worth stating separately. Thinking
content averages 1810 characters against 486 for the visible answer — **3.7x** —
and correlates with total latency at r=0.90. Of the full 32.6s, only 3.7s
happens after the answer starts streaming. Compressing the visible answer
therefore barely moves total latency; the real lever is `enable_thinking` on
the answer call.

Methodology, full dataset, and raw transcripts: [`eval/report.md`](eval/report.md),
[`eval/dataset.py`](eval/dataset.py), [`eval/results.json`](eval/results.json).
Re-run against a live backend with `python eval/run_eval.py --routing-samples 3`.

**Honesty notes:** the corpus is the project's own bundled test data (some
AI-generated, dated in the future) — RAG accuracy measures faithfulness to
the indexed corpus, not validation against real-world financial data.

## Known Limitations

- **Three stable routing failures** — the ones that fail on all 3 samples, so they are real rather than sampling noise. `route-05` ("what is free cash flow?") adds an unnecessary `web_search` to a concept question the knowledge base already answers; `route-11` ("any important global financial news today?") calls no tool at all; `route-17` sends the news half of a compound question to `rag_search` instead of `web_search`. One fix attempt was reverted: routing by time words ("recent", "latest", "today") repaired `route-11` and `route-17` but broke a control question asking about a *recent* 8-K, which is an archived filing rather than live news. The boundary has to be drawn by where the answer lives — archived documents to `rag_search`, live real-world state to `web_search` — not by whether the question sounds recent.
- **File upload PDF parsing** — the DeepDoc PDF pipeline is wired for user-uploaded filings via `/upload_files`, but the bulk corpus indexer (`scripts/index_finance.py`) parses SEC EDGAR filings from their native HTML (iXBRL) form directly rather than through the PDF pipeline, since EDGAR doesn't serve modern filings as PDF (see the module docstring in `index_finance.py`).
- **Extraction only triggers on a turn count, not session end** — there's no reliable "session ended" signal in this request-response architecture (no persistent connection to hook), so memory extraction fires every 5 turns rather than on the OR'd "session end or N turns" condition an earlier design sketch assumed. A conversation that ends on turn *N*-1 within a window never gets that tail extracted.
- **`BackgroundTasks` extraction isn't persisted or retried** — if the process restarts between scheduling and running an extraction, that batch of facts is lost; the next 5-turn boundary in the same session is unaffected (windows don't overlap), so this bounds to "some memory not captured," not corruption.
- **Ticker-vs-acronym ambiguity in the recall path** — the CJK-tolerant ticker extractor used for conclusion recall (not the stricter one `finance_tool()` uses on already-decomposed sub-questions) can't distinguish a common finance acronym from a same-spelled real ticker (`AI` is both "artificial intelligence" and C3.ai); worst case is an irrelevant old conclusion surfacing as background context, which the recall prompt already treats as possibly-stale.
- **Single-user assumption baked into memory recall** — `chat_rt.py`'s hardcoded `USER_ID` is used for profile recall, while extraction derives the writing user from the session's own row; these coincide today but would need reconciling before any real multi-user support.
- **Chat UI is not mobile-adapted** — the core chat layout (`components/page-layout`) has a hard `min-width: 600px` on the main content area plus a fixed `408px` side panel; on a real phone viewport this overflows/squeezes rather than reflowing. The landing page is reasonably responsive on its own, but the global layout shell (`layout/base`) wraps every route in a fixed `100px` sidebar regardless of viewport width. No `@media` breakpoints cover the chat page today — desktop is the only fully supported target.
- **No conversation-history UI** — `session_id` lives only in the URL (`/chat/:id`), not in `localStorage`; there's no way to browse or delete past sessions from the app itself (a `DELETE /sessions` endpoint exists server-side but nothing in the frontend calls it). Every visit starts a fresh session; old ones persist in Postgres indefinitely with no TTL/cleanup.

## Roadmap

The current MVP covers single-ticker stock/market analysis (AAPL/MSFT/GOOGL).
That's architecturally a foundation for a broader investing research
copilot — portfolio-level reasoning and multi-asset comparison — reusing the
same tool/RAG layer.

## License / Attribution

Application and agent code is original; the hybrid retrieval (`rag_search`
in `agent.py`) is hand-rolled directly on native Elasticsearch, with no
RAGFlow dependency. The PDF parsing pipeline (`service/core/deepdoc`,
`service/core/rag`), however, is ported from
[RAGFlow](https://github.com/infiniflow/ragflow) (Apache License 2.0,
Copyright The InfiniFlow Authors) — see the license headers in that
directory. Finance filings via [SEC EDGAR](https://www.sec.gov/edgar),
market data via [yfinance](https://github.com/ranaroussi/yfinance). LLMs via
Alibaba Cloud DashScope.
