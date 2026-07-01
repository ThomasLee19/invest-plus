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
  (bounded by a safety cap so it can't loop forever). No hardcoded
  decision tree — every continue/stop/retry choice comes from the LLM's own
  judgment.
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
DATABASE_URL=postgresql://postgres:pg123456@localhost:5432/investplus
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
```bash
cd frontend
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
This mechanism was validated against a Chinese conversational query on an
English-source corpus: BM25-only recall was **0%**, while hybrid (BM25 +
vector) recall was **100%** — the retrieval layer itself is unchanged from
that validation and carries the same behavior into the finance domain.

## Tech Stack

| Layer | Technology | Role |
|---|---|---|
| LLM | Qwen — qwq-plus (final answer), qwen-plus (plan/reflection) via DashScope | Reasoning + tool decisions |
| Agent Framework | Custom Plan→Act→Reflect→Answer pipeline (no LangChain) | Tool orchestration + self-correction |
| Knowledge Base | Elasticsearch `finance_kb` (SEC filings + news + educational + user uploads) | Hybrid retrieval (BM25 + vector) |
| Real-time Data | yfinance (`service/finance/finance_tool.py`) | Quote / fundamentals / news |
| Document Parsing | DeepDoc (layout/table-transformer/OCR, onnxruntime) | PDF filing uploads → table-aware chunks |
| Web Search | Serper API | Latest market moves / fallback |
| Backend | FastAPI + PostgreSQL | API, SSE, sessions & messages |
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
│       │   ├── agent/agent.py       # Agent pipeline (Plan→Act→Reflect→Answer)
│       │   ├── finance/              # finance_tool.py — live yfinance quote/fundamentals/news
│       │   ├── web_search/          # Serper web search tool
│       │   └── core/
│       │       ├── file_parse.py    # .txt/.md chunker + .pdf DeepDoc pipeline -> ES indexer
│       │       ├── deepdoc/         # PDF parser (layout/table/OCR)
│       │       └── rag/             # Tokenizer/nlp utils + res/deepdoc model weights
│       ├── schemas/chat.py
│       └── utils/database.py
│   └── tests/
│       ├── test_agent_loop.py       # Loop-mechanism unit tests (should_continue, error propagation)
│       └── test_e2e_finance.py      # Live end-to-end smoke test against a running backend
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

## Known Limitations

- **Finance KB retrieval gaps** — a fixed 9-query eval against the live `finance_kb` index measured 7/9 (78%) recall; the 2 misses are thin filings (e.g. a 7-chunk 8-K) or generically-phrased queries getting crowded out by much larger filings in the same shared, un-filtered-by-ticker index. Documented as a real retrieval-quality gap, not a bug.
- **File upload PDF parsing** — the DeepDoc PDF pipeline is wired for user-uploaded filings via `/upload_files`, but the bulk corpus indexer (`scripts/index_finance.py`) parses SEC EDGAR filings from their native HTML (iXBRL) form directly rather than through the PDF pipeline, since EDGAR doesn't serve modern filings as PDF (see the module docstring in `index_finance.py`).

## Roadmap

The current MVP covers single-ticker stock/market analysis (AAPL/MSFT/GOOGL).
That's architecturally a foundation for a broader investing research
copilot — portfolio-level reasoning and multi-asset comparison — reusing the
same tool/RAG layer.

## License / Attribution

Application and agent code is original; the hybrid retrieval is hand-rolled
on native Elasticsearch (no RAGFlow). Finance filings via
[SEC EDGAR](https://www.sec.gov/edgar), market data via
[yfinance](https://github.com/ranaroussi/yfinance). LLMs via Alibaba Cloud
DashScope.
