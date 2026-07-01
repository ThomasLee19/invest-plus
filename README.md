# Invest+ — Finance Research Agent (migrated from a Pokemon battle-advisor)

Invest+ is a RAG + agent system repurposed from a Gen 9 Pokémon competitive
battle Q&A agent into a finance research assistant, **reusing the same agent
architecture, retrieval infrastructure, and backend/frontend shell** — only
the domain layer (tools, RAG corpus, prompts) changed. The migration itself
was the interesting part: it was a live test of how much of an agent system
is genuinely domain-agnostic versus how much was secretly coupled to its
first use case.

**Migration status** (see [`.omc/plans/finance-agent-migration-plan.md`](.omc/plans/finance-agent-migration-plan.md) for the full plan):
- ✅ **Phase 1 — Agent loop architecture upgrade.** The original loop ran a
  single hardcoded reflection pass and silently swallowed tool errors — not
  actually agentic. Rewrote it into a genuinely LLM-driven iterative loop
  (the model itself decides when to call another tool, retry a failed one, or
  stop) with a bounded safety cap distinguishable from a real LLM-signaled
  stop. Verified with 11 unit tests, architect-reviewed.
- ✅ **Phase 2 — Finance data & tools.** Replaced the PokeAPI tool with a live
  yfinance-backed market-data tool (`finance_query`: quote/fundamentals/news);
  ported FinReportRAG's DeepDoc table-aware PDF parser into the upload
  pipeline; built a finance RAG corpus (SEC filings + news + educational
  content) indexed into the renamed `finance_kb` ES index.
- ✅ **Phase 3 — Prompt retargeting.** Plan/reflect/final-answer prompts
  rewritten for finance terminology (tickers, filings, P/E ratio, risk
  factors), preserving the Phase 1 loop structure unchanged.
- ✅ **Phase 4 — Frontend re-skin.** Swapped UI copy/examples in
  [`frontend/src/i18n.tsx`](frontend/src/i18n.tsx) from Pokemon to finance
  (tagline, banner, hot questions spanning filing/news/price/educational
  queries against AAPL/MSFT/GOOGL) — copy-only change, no layout/component
  edits.
- ✅ **Phase 5 — End-to-end verification.** Drove the live stack (real LLM,
  yfinance, and `finance_kb` calls) through three scenarios: an AAPL
  multi-tool query showing runtime-decided tool sequencing with LLM-stated
  rationale, an MSFT single-fact query resolving in exactly one tool call,
  and an invalid-ticker query showing the agent observe and report a tool
  failure instead of crashing or fabricating data. All three passed; see
  [`.omc/eval/phase5_e2e_verification.md`](.omc/eval/phase5_e2e_verification.md).

**The full stack now answers finance questions end to end, verified live**
(tools, RAG corpus, prompts, frontend copy, and the runtime agent loop are
all finance-domain and confirmed working against the real stack) — the
sections below describe the current finance-domain state.

## Highlights

- **Self-designed agent loop** — Plan → Act → Reflect → Answer, hand-built (no LangChain), with autonomous tool selection, self-correction, and a genuinely LLM-driven continue/stop/retry decision at every step.
- **Cross-lingual hybrid retrieval** — a Chinese conversational query scores **0% effective recall with BM25-only → 100% with hybrid (BM25 + vector kNN)** against an English-source corpus.
- **Bilingual, streaming, full-stack** — SSE streaming with a visible reasoning chain; auto language detection; shipped end-to-end (FastAPI + React + ES + PostgreSQL + Docker).
- **Finance RAG corpus** — SEC filings (10-K/10-Q/8-K), news, and educational content for AAPL/MSFT/GOOGL, plus PDF upload support via a ported table-aware DeepDoc parser.

## Features (finance domain — Phases 1-4 complete)

- **Autonomous Agent Pipeline** — Plan → Act → Reflect → Answer; no manual tool selection needed; the Reflect stage loops until the LLM itself judges the answer complete (Phase 1).
- **Three Tools**
  - `rag_search` — Finance knowledge base: SEC filings, news, educational content (ES hybrid search: BM25 + vector kNN)
  - `finance_query` — Real-time market data: quote, fundamentals, news (yfinance)
  - `web_search` — Latest market moves / knowledge-base gaps (Serper API)
- **Streaming Output** — SSE streaming with visible agent reasoning chain (qwq-plus thinking tokens).
- **Multi-turn Conversation** — Session-scoped history; each new session starts fresh.
- **Bilingual** — Auto-detects input language; responds in Chinese or English; UI supports 中/EN toggle.
- **File Upload & Management** — Upload `.txt` / `.md` / `.pdf` filings (PDFs parsed with the ported DeepDoc layout/table pipeline, indexed into ES); view and delete via the Docs page.

## Tech Stack

| Layer | Technology | Role |
|---|---|---|
| LLM | Qwen — qwq-plus (final answer), qwen-plus (plan/reflection) via DashScope | Reasoning + tool decisions |
| Agent Framework | Custom Plan→Act→Reflect→Answer pipeline (no LangChain) | Tool orchestration + self-correction |
| Knowledge Base | Elasticsearch `finance_kb` (SEC filings + news + educational + user uploads) | Hybrid retrieval (BM25 + vector) |
| Real-time Data | yfinance (`service/finance/finance_tool.py`) | Quote / fundamentals / news |
| Document Parsing | DeepDoc (ported from FinReportRAG: layout/table-transformer/OCR, onnxruntime) | PDF filing uploads → table-aware chunks |
| Web Search | Serper API | Latest market moves / fallback |
| Backend | FastAPI + PostgreSQL | API, SSE, sessions & messages |
| Frontend | React + TypeScript + Vite + Ant Design + Valtio | Chat UI, streaming render, doc mgmt |
| Infrastructure | Docker Compose (ES + PG) | Local dependencies |

## Agent Pipeline

```
User question
      ↓
  agent_plan()         ── LLM decides which tools to call, breaks into sub-questions
      ↓
  process_actions()    ── calls rag_search / finance_query / web_search; tool errors
      ↓                    are surfaced to the LLM, not swallowed (Phase 1)
  should_continue()     ── LOOPS: LLM judges if info is sufficient; if not, decides what
      ↓  (bounded loop)    to call next — the loop body, not the LLM, only caps runaway
      ↓                    iterations as a safety net
  final_answer()        ── qwq-plus streams reasoning + answer via SSE
      ↓
  Frontend renders thinking chain + final answer
```

**Tool selection rules (finance domain):**
- Real-time quote / market cap / P-E ratio / fundamentals / news headlines → `finance_query`
- Filing content / risk factors / news analysis / concept explanations → `rag_search`
- Latest market-wide events not covered by the knowledge base → `web_search`
- Off-topic questions (non-finance) → rejected

## Core Technical Deep-Dive

### Agent loop: from scripted pipeline to genuine agent (Phase 1)

The original loop called `reflection()` exactly once after the initial tool
calls, then stopped — a fixed 2-stage pipeline regardless of the question.
Tool exceptions were caught and printed, never surfaced to the model. Only
the final answer's reasoning was streamed to the frontend.

Phase 1 replaced this with `should_continue()`: a bounded `while` loop where
every continue/stop/retry decision is read from the LLM's own structured
judgment (`{sufficient, rationale, actions}`), not from hardcoded branching.
A safety cap (5 iterations) bounds runaway loops without being mistaken for
genuine LLM judgment — cap-stops are logged distinctly from LLM-signaled
stops. Tool failures now land in the conversation memory the LLM sees, so it
can retry, fall back, or flag an incomplete answer instead of the backend
silently hiding the failure. Verified with 11 unit tests run against mocked
LLM responses (no live network calls), architect-reviewed for genuine
LLM-drivenness.

### Cross-lingual hybrid retrieval

`rag_search` combines two signals over the same ES index (native ES 8.11 `knn` + `query`,
hand-rolled — no RAGFlow dependency):

- **BM25** (`content_ltks` full-text) — precise keyword matches (move / Pokémon names).
- **Vector kNN** (`q_1024_vec`, text-embedding-v3, cosine) — semantic & cross-lingual matches.

Scores from both branches are summed (vector branch boosted to balance magnitudes). If query
embedding fails, it degrades gracefully to BM25-only.

**Why it matters:** a Chinese conversational query like *"耐久型坦克怎么配招"* (how to build a
bulky tank) returns **zero** BM25 hits against the English-source corpus, yet vector kNN
correctly surfaces the relevant strategy chunks — effective recall goes from **0% → 100%**.
Similarly *"烈咬陆鲨"* cross-matches the English `garchomp.md`. This retrieval layer carries
forward unchanged into the finance domain.

## Quick Start

### Prerequisites
- Docker Desktop (with WSL integration enabled, if on WSL2)
- Python 3.11+ (conda env recommended)
- Node.js 18+
- DashScope API key (Alibaba Cloud) and Serper API key

### 1. Environment Variables
Copy `.env.example` to `.env` and fill in:
```env
DASHSCOPE_API_KEY=your_dashscope_key
DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
SERPER_API_KEY=your_serper_key
ES_URL=http://localhost:1200
DATABASE_URL=postgresql://postgres:pg123456@localhost:5432/investplus
```

### 2. Start Infrastructure
```bash
docker-compose up -d
```

### 2b. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 3. Fetch and Index the Finance Corpus
```bash
python scripts/fetch_filings.py       # SEC EDGAR filings (10-K/10-Q/8-K) -> data/filings/
python scripts/fetch_news.py          # recent news per ticker -> data/news/
python scripts/fetch_educational.py   # curated reference articles -> data/educational/
python scripts/index_finance.py       # chunk + embed + index all three into ES `finance_kb`
```
(The pre-migration Pokemon-domain corpus/scripts are quarantined under `legacy/` for reference only.)

### 4. Start Backend
```bash
cd backend/app
uvicorn app_main:app --reload --port 8000
```

### 5. Start Frontend
```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5181](http://localhost:5181)

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
│       │   ├── agent/agent.py       # Agent pipeline (Plan→Act→Reflect→Answer, finance-retargeted)
│       │   ├── finance/              # finance_tool.py — live yfinance quote/fundamentals/news
│       │   ├── pokeapi/             # dead code, no longer imported (pre-migration PokeAPI tool)
│       │   ├── web_search/          # Serper web search tool
│       │   └── core/
│       │       ├── file_parse.py    # .txt/.md chunker + .pdf DeepDoc pipeline -> ES indexer
│       │       ├── deepdoc/         # Ported FinReportRAG PDF parser (layout/table/OCR)
│       │       └── rag/             # Ported tokenizer/nlp utils + res/deepdoc model weights
│       ├── schemas/chat.py
│       └── utils/database.py
│   └── tests/
│       └── test_agent_loop.py       # Loop-mechanism unit tests (should_continue, error propagation)
├── frontend/
│   └── src/
│       ├── i18n.tsx                 # Bilingual text (zh/en) — still Pokemon examples, Phase 4
│       ├── components/
│       │   ├── header-bar/          # Header with 中/EN toggle
│       │   └── sender/              # Input box + file attachment
│       └── pages/
│           ├── chat/                # Chat page with SSE streaming
│           └── repository/          # Document management
├── scripts/                          # Finance corpus fetch/index scripts (fetch_filings/news/educational, index_finance)
├── data/                             # Fetched finance corpus (filings/news/educational), indexed into `finance_kb`
├── legacy/                          # Quarantined pre-migration Pokemon-domain data/scripts (reference only)
│   ├── fetch_pokemon_data.py
│   ├── scrape_smogon.py
│   ├── index_smogon.py
│   ├── index_pokemon.py
│   ├── pokemon-data/                # 1025 PokeAPI species dumps (debug cache, not indexed)
│   └── smogon-data/                 # ~20 curated Smogon strategy articles (retired RAG corpus)
├── docker-compose.yml               # ES + PostgreSQL
└── .env                             # API keys and config
```

## Known Limitations

- **Finance KB retrieval gaps** — a fixed 9-query eval (`.omc/eval/finance_eval_set.md`) against the live `finance_kb` index measured 7/9 (78%) recall; the 2 misses are thin filings (e.g. a 7-chunk 8-K) or generically-phrased queries getting crowded out by much larger filings in the same shared, un-filtered-by-ticker index. Documented as a real retrieval-quality gap, not a bug.
- **File upload PDF parsing** — the DeepDoc PDF pipeline is wired for user-uploaded filings via `/upload_files`, but the bulk corpus indexer (`scripts/index_finance.py`) parses SEC EDGAR filings from their native HTML (iXBRL) form directly rather than through the PDF pipeline, since EDGAR doesn't serve modern filings as PDF (see the module docstring in `index_finance.py`).

## Roadmap

1. ~~**Phase 2 — Finance data & tools**~~ ✅ done: live market-data tool (price/fundamentals/news) replacing PokeAPI; ported FinReportRAG's table-aware document parser for financial filings; finance RAG corpus (filings + news + educational content).
2. ~~**Phase 3 — Prompt retargeting**~~ ✅ done: plan/reflect/final-answer prompts rewritten for finance terminology, preserving the Phase 1 iterative loop structure.
3. ~~**Phase 4 — Frontend re-skin**~~ ✅ done: UI copy, i18n strings, and example questions updated to finance (tagline, banner, hot questions).
4. ~~**Phase 5 — End-to-end verification**~~ ✅ done: live-stack scenarios for multi-tool sequencing, single-tool-call simple queries, and invalid-ticker error adaptation, all passed; see [`.omc/eval/phase5_e2e_verification.md`](.omc/eval/phase5_e2e_verification.md).
5. **Beyond Phase 5** — the MVP (single-ticker stock/market analysis) is architecturally a foundation for a broader investing research copilot (portfolio-level reasoning, multi-asset comparison), reusing the same tool/RAG layer.

Full plan, acceptance criteria, and architecture decisions: [`.omc/plans/finance-agent-migration-plan.md`](.omc/plans/finance-agent-migration-plan.md).

## License / Attribution

Application and agent code is original; the hybrid retrieval is hand-rolled on native
Elasticsearch (no RAGFlow). Finance filings via [SEC EDGAR](https://www.sec.gov/edgar),
market data via [yfinance](https://github.com/ranaroussi/yfinance), PDF parsing ported
from FinReportRAG. Pokémon data (pre-migration corpus, now in `legacy/`) via
[PokeAPI](https://pokeapi.co/); strategy content from [Smogon](https://www.smogon.com/);
LLMs via Alibaba Cloud DashScope.
