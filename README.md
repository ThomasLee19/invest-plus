# Invest+ — AI Finance Research Assistant

Invest+ is an autonomous research agent for US equities. Ask it about a stock
in plain English or Chinese, and it plans its own research, pulls live
market data, searches SEC filings and news, and streams back a sourced
answer — deciding for itself which tools to use and when it has enough
information to stop.

## Features

- **Autonomous agent pipeline** — Plan → Act → Reflect → Answer. The agent
  decides which tools to call, breaks questions into sub-queries, and keeps
  reflecting/gathering more information until it judges the answer complete
  (bounded by a safety cap so it can't loop forever — if the cap is hit
  before the LLM signals completion, the final answer discloses that
  information may be incomplete rather than presenting a partial result as
  exhaustive). No hardcoded decision tree — every continue/stop/retry choice
  comes from the LLM's own judgment.
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
  statement, industry comparison, risk scan) that a classification step can
  load one or two of at once, injected into the planning prompt so they
  actually change which sub-questions get asked — verified with a live
  before/after eval, not just a prompt-assembly test (see
  [Quantitative Evaluation](#quantitative-evaluation)).
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
docker-compose up -d
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

## How It Works

```
User question
      ↓
  agent_plan()         ── LLM decides which tools to call, breaks into sub-questions
      ↓
  process_actions()    ── calls rag_search / finance_query / web_search; tool errors
      ↓                    are surfaced to the LLM, not swallowed
  should_continue()     ── LOOPS: LLM judges if info is sufficient; if not, decides what
      ↓  (bounded loop)    to call next — the loop body, not the LLM, only caps runaway
      ↓                    iterations as a safety net
  final_answer()        ── streams reasoning + answer via SSE
      ↓
  Frontend renders thinking chain + final answer
```

**Tool selection rules:**
- Real-time quote / market cap / P/E ratio / fundamentals / news headlines → `finance_query`
- Filing content / risk factors / news analysis / concept explanations → `rag_search`
- Latest market-wide events not covered by the knowledge base → `web_search`
- Off-topic (non-finance) questions → rejected

**Why the loop is a genuine agent loop, not a scripted pipeline:** every
continue/stop/retry decision is read from the LLM's own structured judgment
(`{sufficient, rationale, actions}`), not from hardcoded branching. A safety
cap (5 iterations) bounds runaway loops without being mistaken for genuine
LLM judgment — cap-stops are logged distinctly from LLM-signaled stops. Tool
failures land in the conversation memory the LLM itself sees, so it can
retry, fall back, or flag an incomplete answer instead of the backend
silently swallowing the failure.

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

**Cross-session memory:** before calling `agent_plan()`, `final_answer()`
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
indicator checklist. `classify_skill()` (`agent.py:782`) is an independent
LLM call — deliberately *not* folded into `agent_plan()`'s own call, because
by the time you know which skill to load it's too late to inject its body
into that same call — that returns zero, one, or (capped in code,
regardless of what the LLM returns) two matching skills; their bodies are
loaded (`load_skill()`, `agent.py:757`) and injected into the planning
prompt as their own labeled sections. This is verified to actually change
tool planning, not just decorate the prompt — see
[Quantitative Evaluation](#quantitative-evaluation).

## Tech Stack

| Layer | Technology | Role |
|---|---|---|
| LLM | Qwen — qwen3.7-max (final answer), qwen-plus (plan/reflection), via the `openai` SDK against DashScope's OpenAI-compatible endpoint | Reasoning + tool decisions |
| Agent Framework | Custom Plan→Act→Reflect→Answer pipeline (no LangChain) | Tool orchestration + self-correction |
| Knowledge Base | Elasticsearch `finance_kb` (SEC filings + news + educational + user uploads); text-embedding-v3 for vector embeddings, qwen3-vl-rerank (native `dashscope` SDK) for reranking | Hybrid retrieval (BM25 + vector) + rerank |
| Real-time Data | yfinance (`service/finance/finance_tool.py`) | Quote / fundamentals / news |
| Document Parsing | DeepDoc (layout/table-transformer/OCR, onnxruntime) | PDF filing uploads → table-aware chunks |
| Web Search | Serper API | Latest market moves / fallback |
| Backend | FastAPI + PostgreSQL | API, SSE, sessions & messages; `user_profiles`/`conclusion_memory` for cross-session memory |
| Memory & Skills | `service/memory/{profile,conclusion,extraction}.py`, `service/agent/skills/*.md` | Cross-session recall, LLM extraction pipeline, SOP-driven planning |
| Frontend | React + TypeScript + Vite + Ant Design + Valtio | Chat UI, streaming render, doc mgmt |
| Infrastructure | Docker Compose (ES + PG) | Local dependencies |

## Project Structure

```
InvestPlus/
├── backend/
│   └── app/
│       ├── app_main.py              # FastAPI entry point
│       ├── router/
│       │   ├── chat_rt.py           # /chat SSE, /upload_files (.txt/.md/.pdf), /get_files, /delete_file
│       │   └── history_rt.py        # /sessions, /messages
│       ├── service/
│       │   ├── agent/
│       │   │   ├── agent.py         # Agent pipeline (Plan→Act→Reflect→Answer) + memory/skill recall & injection
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
│   └── src/
│       ├── i18n.tsx                 # Bilingual text (zh/en)
│       ├── components/
│       │   ├── header-bar/          # Header with 中/EN toggle
│       │   └── sender/              # Input box + file attachment
│       └── pages/
│           ├── chat/                # Chat page with SSE streaming
│           └── repository/          # Document management
├── scripts/                          # Finance corpus fetch/index scripts (fetch_filings/news/educational, index_finance)
├── data/                             # Fetched finance corpus (filings/news/educational), indexed into `finance_kb`
├── docker-compose.yml               # ES + PostgreSQL
└── .env                             # API keys and config
```

## Quantitative Evaluation

A reproducible evaluation harness (`eval/`) drives the live backend
end-to-end (real agent/RAG/Elasticsearch logic, no mocks) against a labeled
dataset built from the actual indexed corpus:

| Metric | Result | Basis |
|---|---|---|
| RAG retrieval/answer accuracy | 14/14 = 100% | fact-based QA pairs checked against the actual filings/news/educational corpus (1 additional question excluded as a flawed test design — see `eval/report.md`) |
| Tool-routing accuracy (lenient — required tool present) | 17/17 = 100% | questions spanning finance_query / rag_search / web_search / no-tool / compound intents |
| Tool-routing accuracy (strict — exact tool set match) | 10/17 = 58.8% | same dataset; the gap reflects a real, documented over-triggering tendency in the Reflect loop, not a routing bug — the required tool is always called, but `web_search` is often additionally (and unnecessarily) triggered as a fallback |
| Response latency | TTFT 2.1s avg; full response p50 29.9s / p90 85.6s | 32 real streaming requests; multi-round Reflect cases drive the long tail |
| Edge-case robustness | 4/4 = 100% (1 case inconclusive — see report) | empty input, oversized input, invalid ticker, non-existent session — all handled gracefully with no 5xx/uncaught exceptions |
| SOP injection lift (single-hit valuation) | baseline 34.3% → injected 69.4% = **+35.2pp** (threshold ≥30pp) → PASS | 12 valuation-only questions, 3 samples/condition averaged, real `qwen-plus` calls through the actual `agent_plan()` |
| SOP injection lift (dual-hit, both SOPs must improve) | 6/7 PASS on the committed run (see `eval/skill_coverage_run.txt`) | 7 compound questions expecting 2 simultaneous SOP hits; the 1 miss (`sop-dual-02`) is a flat 6%→0% on a dimension both conditions phrased identically generically ("MSFT fundamentals") — diagnosed as scorer blind-spot + single-condition sampling noise, not a functional regression (the *other* SOP dimension on that same question jumped 17%→100%). An independent re-run during review, with a fresh 3-sample draw, cleared 7/7 — consistent with the noise diagnosis, not a "fixed" result overwriting this one |

Methodology, full dataset, and raw transcripts: [`eval/report.md`](eval/report.md),
[`eval/dataset.py`](eval/dataset.py), [`eval/results_final.json`](eval/results_final.json).
Re-run against a live backend with `python eval/run_eval.py`.

SOP-coverage methodology, dataset, and raw per-question transcripts:
[`eval/skill_coverage_eval.py`](eval/skill_coverage_eval.py),
[`eval/skill_coverage_dataset.py`](eval/skill_coverage_dataset.py),
[`eval/skill_coverage_raw.json`](eval/skill_coverage_raw.json). Re-run with
`python eval/skill_coverage_eval.py` (needs a live DashScope key; ~170 real
`qwen-plus` calls at 3 samples/condition).

**Honesty notes:** the corpus is the project's own bundled test data (some
AI-generated, dated in the future) — RAG accuracy measures faithfulness to
the indexed corpus, not validation against real-world financial data.

## Known Limitations

- **Tool over-triggering in the Reflect loop** — as measured above, the agent's strict tool-routing accuracy (58.8%) trails its lenient accuracy (100%): it reliably calls the *required* tool but often calls `web_search` as an extra, unneeded fallback, adding latency/cost without changing correctness. A real efficiency target, not a routing bug.
- **File upload PDF parsing** — the DeepDoc PDF pipeline is wired for user-uploaded filings via `/upload_files`, but the bulk corpus indexer (`scripts/index_finance.py`) parses SEC EDGAR filings from their native HTML (iXBRL) form directly rather than through the PDF pipeline, since EDGAR doesn't serve modern filings as PDF (see the module docstring in `index_finance.py`).
- **Extraction only triggers on a turn count, not session end** — there's no reliable "session ended" signal in this request-response architecture (no persistent connection to hook), so memory extraction fires every 5 turns rather than on the OR'd "session end or N turns" condition an earlier design sketch assumed. A conversation that ends on turn *N*-1 within a window never gets that tail extracted.
- **`BackgroundTasks` extraction isn't persisted or retried** — if the process restarts between scheduling and running an extraction, that batch of facts is lost; the next 5-turn boundary in the same session is unaffected (windows don't overlap), so this bounds to "some memory not captured," not corruption.
- **Ticker-vs-acronym ambiguity in the recall path** — the CJK-tolerant ticker extractor used for conclusion recall (not the stricter one `finance_tool()` uses on already-decomposed sub-questions) can't distinguish a common finance acronym from a same-spelled real ticker (`AI` is both "artificial intelligence" and C3.ai); worst case is an irrelevant old conclusion surfacing as background context, which the recall prompt already treats as possibly-stale.
- **Single-user assumption baked into memory recall** — `chat_rt.py`'s hardcoded `USER_ID` is used for profile recall, while extraction derives the writing user from the session's own row; these coincide today but would need reconciling before any real multi-user support.

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
