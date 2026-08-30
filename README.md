[English](README.md) | [简体中文](README.zh-cn.md)

<p align="center">
  <img src="./assets/readme/hero.svg" width="100%"
       alt="Invest+ — ask it about a US-listed stock; it plans its own research and knows when to stop. Beside the name, the append-only trajectory: a static prefix, the user question, then one appended row per round, ending on a round with no tool calls.">
</p>

# Invest+ — AI Finance Research Assistant

Ask it about a US-listed stock in plain English or Chinese. It plans its own
research, pulls live market data, searches SEC filings and news, and streams
back a sourced answer — deciding for itself which tools to call and when it
has enough to stop.

The loop, the hybrid retrieval, and the cross-session memory are all
hand-rolled — no agent framework. Every effect claimed below is measured, and
the measurements that turned out not to be trustworthy are published as such.

[![License: MIT](https://img.shields.io/badge/license-MIT-35322e.svg)](LICENSE)
[![Build and Deploy](https://github.com/ThomasLee19/invest-plus/actions/workflows/deploy.yml/badge.svg)](https://github.com/ThomasLee19/invest-plus/actions/workflows/deploy.yml)

## Try it live

### [investplus-agent.com](https://investplus-agent.com)

No signup. Ask it something from the examples on the landing page, or paste
your own question. Rate-limited to 20 req/min as light friction against
automated traffic — not a real access-control layer.

<p align="center">
  <img src="./assets/readme/showcase.png" width="100%"
       alt="The Invest+ landing page: a single input box under the prompt What are we researching today, five example questions about filings, quotes and news, and a 中/EN toggle in the header.">
</p>

Running it locally needs Docker, Elasticsearch, PostgreSQL, two API keys and a
corpus indexing pass. [Quick Start](#quick-start) has the short path.

<!-- ROUND2-PLACEHOLDER: assets/readme/answer.png — a real answer frame:
     the thinking chain, the answer with its citation markers, and the sources
     panel in one shot. The landing shot above shows the product exists; this
     one would show the mechanism the section below measures. -->

## What the measurements say

Every number below comes from a reproducible harness in [`eval/`](eval/) that
drives the live backend end-to-end — real agent, real retrieval, real
Elasticsearch, no mocks.

| What was measured | Result | Measurement conditions | Source |
|---|---|---|---|
| Cross-lingual retrieval recall | BM25-only **0/10** → hybrid **10/10** | 10 Chinese conversational finance questions against this project's English-only corpus; same query-construction code path `rag_search` uses in production | [`eval/recall_validation.py`](eval/recall_validation.py) |
| Tool-routing hit rate | **74.5%** average | 17 questions × 3 samples. 10 stable hits, 3 stable failures, **4 questions that flip** on identical code. Single-sample figures carry ~±24pp of swing and are not reported | [`eval/report.md`](eval/report.md) |
| First substantive judgement | **2.93s** avg (p50 2.63s / p90 4.86s) | `POST /chat` → first tool-call event, n=24. This is the responsiveness number | [`eval/report.md`](eval/report.md) |
| Full response latency | **32.6s** avg (p50 31.9s / p90 55.0s) | 32 real streaming requests, start to end of streamed answer | [`eval/results.json`](eval/results.json) |
| RAG answer accuracy | **13/15** | Fact-based QA pairs checked against the indexed corpus. Reported on all 15 asked. One of them (`rag-11`) was judged mis-designed — its ground truth is a time snapshot while the question asks a floating relative concept — and excluding it gives 13/14; the conservative figure is the one quoted here | [`eval/report.md`](eval/report.md) |
| Edge-case robustness | **5/5** | Empty input, oversized input, invalid ticker, off-topic question, non-existent session | [`eval/report.md`](eval/report.md) |
| Loop rewrite, before → after | Tool calls **77 → 34**, average wall time **108.7s → 75.3s** | Same 5 questions, one run each, both deep enough to reach follow-up rounds (23 vs 19 follow-up calls). Strict and near-duplicate tool calls measured **0 in both** — see [the rewrite note](#1-a-real-agent-loop-not-a-scripted-pipeline) | [`repeat_probe_master-original.md`](eval/repeat_probe_master-original.md), [`repeat_probe_increment-2.md`](eval/repeat_probe_increment-2.md) |

Re-run it yourself against a live backend:

```bash
python eval/run_eval.py --routing-samples 3
```

### Where the latency actually goes

The two latency rows above say how long it takes; this says what to do about
it. Across the same 32 requests, thinking content averages **1810 characters**
against **486** for the visible answer — a 3.7x gap. The visible answer is not
where the clock goes either: only **11%** of the total 32.6s elapses after the
answer has started streaming.

The two lengths do not carry latency equally. Thinking length correlates with
total latency at **r = 0.90**; visible answer length correlates at only
**r = 0.68**. So shortening the answer — the obvious first move — buys almost
nothing. The lever that matters is `enable_thinking` on the answer call.

Both correlations are computed from the per-request `thinking_chars`, `answer`
and `total_latency` fields in [`eval/results.json`](eval/results.json), so the
figures can be recomputed rather than taken on trust.

### Numbers this project does not claim

Three measurements were built, run, and then disqualified. They are recorded
here rather than quietly dropped, because each one would have flattered the
project.

- **"Time to first token."** Since `448b831` the first SSE event is an
  acknowledgment emitted *before* any LLM call, so it measures a constant
  0.00s. It proves the connection opened; it says nothing about the model,
  retrieval, or tools. Quote "first substantive judgement" instead.
- **Single-sample routing accuracy.** 4 of 17 questions flip run-to-run on
  identical code, putting roughly **±24 percentage points** of swing on any
  single-sample figure. Any before/after comparison narrower than that band is
  unreadable, so only the multi-sample average is reported.
- **SOP injection coverage lift.** Both rulers are known broken. The original
  counted keywords in generated sub-questions — but `finance_query` does not
  parse specific metrics, so `"AAPL PE ratio"` and `"AAPL fundamentals"` return
  byte-identical results; it was rewarding verbosity, not information.
  Rescoring on what the tools actually returned dropped the lift from +52.8pp
  to +11.1pp — but the new ruler saturates too, since the fundamentals card
  always carries exactly 2 of the 5 valuation concepts. Redesigning the scoring
  dimensions is outstanding work.

**Corpus honesty note:** `data/` is the project's own bundled test corpus, some
of it AI-generated and dated in the future. RAG accuracy measures faithfulness
to the indexed corpus — not validation against real-world financial data.

## What it is

A research agent over three tools and one knowledge base. `rag_search` does
hybrid retrieval over SEC filings (10-K/10-Q/8-K), news, and educational
reference articles; `finance_query` pulls live quotes, fundamentals and news
from yfinance; `web_search` covers market-wide events the corpus doesn't hold.
A fourth tool, `load_sop`, loads a research playbook rather than fetching data.

It detects Chinese or English input and answers in kind, streams its reasoning
chain alongside the answer over SSE, remembers you across sessions, and accepts
your own `.txt` / `.md` / `.pdf` filings as additional context. Every answer
ends with a disclaimer appended by code after generation — not requested in a
prompt, so the model cannot drop it.

## Why it's different

### 1. A real agent loop, not a scripted pipeline

<p align="center">
  <img src="./assets/readme/agent-loop.svg" width="100%"
       alt="The decision loop: one LLM call decides each round; if it emits tool calls a tool runs and the result is appended to the trajectory, which returns to the same decision operation. A round with no tool calls is the only normal exit. A round cap forces a stop, and the answer discloses it.">
</p>

<details>
<summary><b>The same loop as text, with the function names and the caching note</b></summary>

```text
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

</details>

Every continue/stop/retry decision comes from the model's own native
`tool_calls` output, not from hardcoded branching — a round with no tool calls
*is* the stop signal. The loop exits on exactly three conditions: no further
tool calls, the round cap, or a call erroring out. A safety cap of 6 decision
rounds (`MAX_DECISION_ROUNDS`, `agent.py:894`) bounds runaway loops — one
planning round plus at most five follow-up rounds. Cap-stops are logged
distinctly from model-signaled stops so the two are never confused, and when
the cap fires first the final answer discloses that information may be
incomplete rather than presenting a partial result as exhaustive. Tool failures
are appended to the trajectory the model itself reads, so it can retry, fall
back, or flag the gap.

`final_answer()` deliberately sits off the trajectory — it buys a
better-quality answer at the cost of an extra round trip and a model that
shares no cache with the loop.

**Tool selection rules:**

| Question shape | Tool |
|---|---|
| Real-time quote / market cap / P/E / fundamentals / news headlines | `finance_query` |
| Filing content / risk factors / news analysis / concept explanations | `rag_search` |
| Latest market-wide events not covered by the knowledge base | `web_search` |
| Off-topic (non-finance) | rejected |

<details>
<summary><b>This shape is a rewrite. What the first version got wrong.</b></summary>

The first version put tool descriptions in the prompt body, had the model emit
JSON text that the backend parsed, and re-serialized accumulated tool results
into a fresh user message each round.

That last part is the failure mode the current design exists to avoid: the
model never saw its own call history, only text reformatted by the application,
so it re-issued calls it had already made. Two layers of deduplication were
added to suppress the symptom. Both were deleted once the trajectory was made
real.

The claim that the trajectory — not the dedup code — was doing the work is
falsifiable, so it was tested by deleting the dedup layers and probing whether
repeats came back. They did not: across 23 follow-up calls on the old shape and
19 on the new one, strict and near-duplicate tool calls both measured 0. What
did move is volume and time — total tool calls 77 → 34, average wall time
108.7s → 75.3s over the same five questions, one run each.

None of that counts until the run is shown capable of detecting a repeat at
all. A batch where no request ever reaches a follow-up round cannot produce a
duplicate call, so "zero repeats" measured on it is not a weak result — it is
no result, supporting and refuting the claim equally. An earlier run was
exactly that case: 0 of 5 requests entered a follow-up round, and its verdict
is filed as *not measured*, not as *not reproduced*. Both runs quoted above
clear that check first, at 5 of 5.

Sample size is still five questions, and this is model behaviour rather than a
deterministic property, so even the passing verdict is recorded as "not
reproduced in this sample", not as proof.

</details>

### 2. Hybrid retrieval that survives a language switch

`rag_search` combines two signals over the same Elasticsearch index — native ES
8.11 `knn` + `query`, hand-rolled, no RAGFlow dependency:

- **BM25** (`content_ltks` full-text) — precise keyword matches.
- **Vector kNN** (`q_1024_vec`, text-embedding-v3, cosine) — semantic and
  cross-lingual matches.

Scores from both branches are summed, with the vector branch boosted to balance
magnitudes; if query embedding fails it degrades gracefully to BM25-only.
Combined candidates are reranked with qwen3-vl-rerank, then an upload-recency
boost narrows the final set to the top 5.

<p align="center">
  <img src="./assets/readme/retrieval.svg" width="100%"
       alt="One query fans out to a BM25 branch and a vector kNN branch over the same index; their scores are summed with the vector branch boosted, reranked, then cut to the top 5. BM25 alone recalled 0 of 10 Chinese questions against the English-only corpus; the hybrid recalled 10 of 10.">
</p>

This is the mechanism behind the 0/10 → 10/10 row in the table above: against
an English-only corpus, Chinese conversational questions are invisible to
keyword search and fully recoverable with the vector branch added.

### 3. Memory that reaches the answer, not just the plan

Before entering the decision loop, `final_answer()` recalls the user's profile
(`recall_user_profile`, `service/memory/profile.py`) and any unexpired research
conclusions for tickers mentioned in the question. Ticker extraction uses a
CJK-tolerant regex (`_extract_tickers_loose`, `agent.py:416`) because
`_TICKER_RE`'s `\b` word boundaries miss tickers glued to Chinese text — e.g.
`AAPL的股价`.

Both are woven into the planning prompt so the agent can skip redundant
fetches, and the recalled conclusions are **also** spliced into the final
answer prompt — so a fact recalled from a prior session can actually appear in
this turn's answer, not merely influence which tools get called. Recalled
content is wrapped in `<untrusted_context>` with an explicit "treat live data
as authoritative if they conflict" instruction, the same convention used for
tool results.

Conclusions carry tiered TTLs — fundamentals and filing facts ~90 days, news
~30 days. Real-time quotes are never persisted as memory; they are recalled
live every time.

<details>
<summary><b>How facts get written, and what stands between the extraction LLM and the database</b></summary>

Every 5 turns a `BackgroundTasks`-scheduled pass
(`service/memory/extraction.py`) reads the recent conversation and asks the LLM
to extract structured facts — updated preferences, timestamped conclusions. It
adds no request latency.

Real-time quote data is dropped by code before it ever reaches validation; it
has no business being cached as long-term memory. What survives is
schema-validated deterministically — enums, ticker and metric-name regexes,
length caps — before being written. A successful prompt injection against the
extraction LLM can therefore produce confusing *content*, but cannot write an
out-of-schema value or escape the sandboxed prompt string.

</details>

### 4. A skill library the model pulls, rather than one the backend pushes

Four research playbooks live as plain Markdown under
`service/agent/skills/` — `valuation.md`, `financial_statement.md`,
`industry_comparison.md`, `risk_scan.md` — each with YAML frontmatter and an
indicator checklist. Only their `name` + `description` pairs are resident in
the decision system prompt as a metadata catalogue; a body enters context only
when the model calls `load_sop`. Measured cost of that split: 813 resident
characters against 3082 characters of bodies, so 26%.

This replaced an unconditional `classify_skill()` round-trip that ran before
every plan. The saving is not on questions that need a playbook — those break
even, one classification call becoming one `load_sop` call — it is that
questions needing no playbook stop paying at all.

Stated honestly, the switch cost some routing recall: positives fell 19/19 →
16/19 while false positives held at 0/16, and only one of those three is a
clean regression — one is a self-contradicting dataset label, and one is a
scoring mismatch, since the old call hard-capped its output at two skills and
`load_sop` has no such cap. Timing is unresolved: the path structurally loses a
whole LLM round trip, but the measurements disagree with each other inside the
sampling noise, so no claim is made either way.

SOP bodies deliberately never enter the memory channel — they are instructions
to the model, not facts about the world, and letting them in would feed the
user's own methodology checklist back to them as cited reference material. A
test pins that.

## Quick Start

**Prerequisites:** Docker Desktop (with WSL integration, if on WSL2),
Python 3.11+, Node.js 18+, a DashScope API key (Alibaba Cloud), a Serper API key.

**1. Environment.** Copy `.env.example` to `.env` and fill in your keys:

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

**2. Infrastructure and dependencies.**

```bash
docker compose up -d
pip install -r requirements.txt
```

**3. Build the knowledge base.** Fetches the corpus and indexes it into the
Elasticsearch index `finance_kb`. One-time, and the slowest step.

```bash
python scripts/fetch_filings.py       # SEC EDGAR 10-K/10-Q/8-K  -> data/filings/
python scripts/fetch_news.py          # recent news per ticker   -> data/news/
python scripts/fetch_educational.py   # reference articles       -> data/educational/
python scripts/index_finance.py       # chunk + embed + index all three
```

**4. Backend.** Note the working directory — imports are flat, so it must run
from `backend/app`, not `backend/`.

```bash
cd backend/app
uvicorn app_main:app --reload --port 8000
```

**5. Frontend.**

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open [http://localhost:5181](http://localhost:5181).

## Tech Stack

| Layer | Technology | Role |
|---|---|---|
| LLM | Qwen — qwen3.7-max (final answer), qwen-plus (decision operation), via the `openai` SDK against DashScope's OpenAI-compatible endpoint | Reasoning + tool decisions |
| Agent | Hand-rolled loop: static prefix + append-only trajectory + native tool calling (no LangChain) | Tool orchestration + self-correction |
| Knowledge base | Elasticsearch `finance_kb` (filings + news + educational + user uploads); text-embedding-v3 for vectors, qwen3-vl-rerank (native `dashscope` SDK) for reranking | Hybrid retrieval (BM25 + vector) + rerank |
| Real-time data | yfinance (`service/finance/finance_tool.py`) | Quote / fundamentals / news |
| Document parsing | DeepDoc (layout / table-transformer / OCR, onnxruntime) | PDF filing uploads → table-aware chunks |
| Web search | Serper API | Latest market moves / fallback |
| Backend | FastAPI + PostgreSQL | API, SSE, sessions & messages; `user_profiles` / `conclusion_memory` |
| Memory & skills | `service/memory/{profile,conclusion,extraction}.py`, `service/agent/skills/*.md` | Cross-session recall, extraction pipeline, SOP-driven planning |
| Frontend | React + TypeScript + Vite + Ant Design + Valtio | Chat UI, streaming render, doc management |
| Infrastructure | Docker Compose (ES + PG for dev; full stack + nginx gateway + Let's Encrypt for prod) | Local dependencies / production hosting |
| CI/CD | GitHub Actions + GHCR | Build/push images on every push; SSH deploy on `master` |

## Production Deployment


The [live demo](#try-it-live) runs from this repo via a second Compose file
layered on the dev one:

- **`docker-compose.prod.yml`** — adds `backend` / `frontend` / `gateway`
  services, pins a `mem_limit` per service (calibrated against measured
  container memory under real load, not guessed), and drops the dev-only host
  port publishing for `es01` / `pg`.
- **`gateway/`** — one nginx container is the only public entry point: TLS
  (Let's Encrypt via `certbot`, two-stage bootstrap to break the
  chicken-and-egg cert/nginx startup order), `/ai-search/*` reverse-proxied to
  the backend with SSE passthrough (buffering off), and request rate limiting.
- **`.github/workflows/deploy.yml`** — on push to `master`: build and push
  `backend` / `frontend` / `gateway` images to GHCR, then SSH in to `pull` +
  `up -d`. The deploy SSH key only ever runs those two commands; business
  secrets (`.env`) are placed on the server by hand once, never transmitted
  through CI.

This is not a generic "deploy anywhere" template. The compose files and gateway
config are written against this project's specific service layout, and the
`mem_limit` values are calibrated for one particular VM size. Treat them as a
worked example, not a drop-in.


## Known Limitations

### Routing and retrieval

- **Three stable routing failures** — the ones that fail on all 3 samples, so
  they are real rather than sampling noise.
- **Ticker-vs-acronym ambiguity in the recall path** — the CJK-tolerant
  extractor can't distinguish a finance acronym from a same-spelled ticker
  (`AI` is both "artificial intelligence" and C3.ai).

<details>
<summary>Detail on both</summary>

`route-05` ("what is free cash flow?") adds an unnecessary `web_search` to a
concept question the knowledge base already answers. `route-11` ("any important
global financial news today?") calls no tool at all. `route-17` sends the news
half of a compound question to `rag_search` instead of `web_search`.

One fix attempt was reverted: routing by time words ("recent", "latest",
"today") repaired `route-11` and `route-17` but broke a control question asking
about a *recent* 8-K — an archived filing, not live news. The boundary has to be
drawn by where the answer lives — archived documents to `rag_search`, live
real-world state to `web_search` — not by whether the question sounds recent.

On the acronym collision: the loose extractor is used only for conclusion
recall, not by `finance_tool()`, which uses a stricter one on already-decomposed
sub-questions. Worst case is an irrelevant old conclusion surfacing as
background context, which the recall prompt already treats as possibly-stale.

</details>

### Memory

- **Extraction triggers on a turn count, not session end** — there is no
  reliable "session ended" signal in a request-response architecture, so it
  fires every 5 turns. A conversation ending on turn *N*-1 never gets its tail
  extracted.
- **`BackgroundTasks` extraction is not persisted or retried** — a process
  restart between scheduling and running loses that batch. Windows don't
  overlap, so this bounds to "some memory not captured", not corruption.
- **Single-user assumption** — `chat_rt.py` hardcodes `USER_ID` for profile
  recall while extraction derives the writing user from the session row. These
  coincide today but would need reconciling before real multi-user support.

### Ingestion

- **PDF parsing covers uploads, not the bulk corpus** — the DeepDoc pipeline is
  wired for user uploads via `/upload_files`, but `scripts/index_finance.py`
  parses SEC filings from their native HTML (iXBRL) instead, because EDGAR
  doesn't serve modern filings as PDF. See the module docstring.

### Frontend

- **The chat UI is desktop-only** — `components/page-layout` has a hard
  `min-width: 600px` plus a fixed `408px` side panel, and `layout/base` wraps
  every route in a fixed `100px` sidebar. No `@media` breakpoints cover the chat
  page; on a phone viewport it overflows rather than reflowing. The landing page
  is responsive on its own.
- **No conversation-history UI** — `session_id` lives only in the URL
  (`/chat/:id`), never in `localStorage`. A `DELETE /sessions` endpoint exists
  server-side but nothing calls it. Every visit starts a fresh session; old ones
  persist in Postgres indefinitely with no TTL.

## Roadmap

The current MVP covers single-ticker stock and market analysis
(AAPL / MSFT / GOOGL). Architecturally that is a foundation for a broader
investing research copilot — portfolio-level reasoning and multi-asset
comparison — reusing the same tool and retrieval layer.

## Project Structure

<details>
<summary><b>Full tree, with per-file notes</b></summary>

```
InvestPlus/
├── backend/
│   ├── Dockerfile                   # Prod image: deps → tiktoken/nltk pre-bake → app code (that layer order gives cache hits on code-only changes)
│   ├── app/
│   │   ├── app_main.py              # FastAPI entry point
│   │   ├── router/
│   │   │   ├── chat_rt.py           # /chat SSE, /upload_files (.txt/.md/.pdf), /get_files, /delete_file
│   │   │   └── history_rt.py        # /sessions, /messages
│   │   ├── service/
│   │   │   ├── agent/
│   │   │   │   ├── agent.py         # Agent loop (decision operation over a trajectory) + memory/skill recall & injection
│   │   │   │   └── skills/          # SOP playbooks: valuation/financial_statement/industry_comparison/risk_scan.md
│   │   │   ├── memory/
│   │   │   │   ├── profile.py       # recall_user_profile / upsert_user_profile
│   │   │   │   ├── conclusion.py    # recall_conclusion_facts / upsert_conclusion_fact (tiered TTL)
│   │   │   │   └── extraction.py    # extract_memory() — every-5-turn LLM extraction pipeline
│   │   │   ├── finance/             # finance_tool.py — live yfinance quote/fundamentals/news
│   │   │   ├── web_search/          # Serper web search tool
│   │   │   └── core/
│   │   │       ├── file_parse.py    # .txt/.md chunker + .pdf DeepDoc pipeline -> ES indexer
│   │   │       ├── deepdoc/         # PDF parser (layout/table/OCR)
│   │   │       └── rag/             # Tokenizer/nlp utils + res/deepdoc model weights
│   │   ├── models/memory.py         # SQLAlchemy models: UserProfile, ConclusionMemory
│   │   ├── schemas/chat.py
│   │   └── utils/database.py
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
├── eval/                            # Quantitative agent/RAG evaluation harness
├── frontend/
│   ├── Dockerfile                   # Multi-stage: npm build -> static assets served by nginx
│   └── src/
│       ├── i18n.tsx                 # Bilingual text (zh/en)
│       ├── styles/tokens.css        # Design tokens — single source of truth, mirrored in tokens.ts
│       ├── components/
│       │   ├── header-bar/          # Header with 中/EN toggle
│       │   └── sender/              # Input box + file attachment
│       └── pages/
│           ├── chat/                # Chat page with SSE streaming
│           └── repository/          # Document management
├── gateway/                         # Prod entry point: nginx TLS/reverse-proxy/rate-limit
│   ├── nginx.conf                   # Production config (TLS, real domain)
│   └── nginx.local.conf             # Local-stack equivalent (plain HTTP, no certbot)
├── diagrams/                        # Architecture / workflow / sequence diagram sources + rendered HTML
├── .github/workflows/deploy.yml     # CI: build 3 images on every push; on master, push to GHCR + SSH deploy
├── scripts/                         # Corpus fetch/index scripts
├── data/                            # Fetched finance corpus, indexed into `finance_kb`
├── docker-compose.yml               # ES + PostgreSQL (shared base)
├── docker-compose.local.yml         # + backend/frontend/gateway for local full-stack dev (plain HTTP)
├── docker-compose.prod.yml          # + backend/frontend/gateway/certbot for production (TLS, mem_limit pins)
└── .env                             # API keys and config
```

</details>

## License / Attribution

Released under the [MIT License](LICENSE) — Copyright (c) 2026 Thomas Lee.
That covers the original application and agent code, including the hybrid
retrieval (`rag_search` in `agent.py`), which is hand-rolled directly on native
Elasticsearch with no RAGFlow dependency.

One directory is not covered by it:

The PDF parsing pipeline (`service/core/deepdoc`, `service/core/rag`) is ported
from [RAGFlow](https://github.com/infiniflow/ragflow) and remains under the
Apache License 2.0, Copyright The InfiniFlow Authors. Every file carrying
code in those two trees has its original license header — the two empty
`__init__.py` package markers do not — and a full copy of the licence sits
alongside them at
[`backend/app/service/core/LICENSE-APACHE-2.0`](backend/app/service/core/LICENSE-APACHE-2.0).
The `.onnx` model weights shipped under those trees are not covered by this
note; their licensing follows upstream RAGFlow and has not been verified here.

Filings via [SEC EDGAR](https://www.sec.gov/edgar), market data via
[yfinance](https://github.com/ranaroussi/yfinance), LLMs via Alibaba Cloud
DashScope.
