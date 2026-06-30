# Invest+ — Finance Research Agent (migrating from a Pokemon battle-advisor)

Invest+ is a RAG + agent system being repurposed from a Gen 9 Pokémon
competitive battle Q&A agent into a finance research assistant, **reusing the
same agent architecture, retrieval infrastructure, and backend/frontend
shell** — only the domain layer (tools, RAG corpus, prompts) is being
replaced. The migration itself is the interesting part: it's a live test of
how much of an agent system is genuinely domain-agnostic versus how much was
secretly coupled to its first use case.

**Migration status** (see [`.omc/plans/finance-agent-migration-plan.md`](.omc/plans/finance-agent-migration-plan.md) for the full plan):
- ✅ **Phase 1 — Agent loop architecture upgrade.** The original loop ran a
  single hardcoded reflection pass and silently swallowed tool errors — not
  actually agentic. Rewrote it into a genuinely LLM-driven iterative loop
  (the model itself decides when to call another tool, retry a failed one, or
  stop) with a bounded safety cap distinguishable from a real LLM-signaled
  stop. Verified with 11 unit tests, architect-reviewed.
- ⏳ **Phase 2 — Finance data & tools.** Replace the PokeAPI tool with a live
  market-data tool; port a second project's (FinReportRAG) table-aware
  document parser for financial filings into this RAG pipeline.
- ⏳ **Phase 3 — Prompt retargeting.** Rewrite the agent's tool-selection and
  reasoning prompts for finance terminology.
- ⏳ **Phase 4 — Frontend re-skin.** Swap UI copy/examples from Pokemon to
  finance.

**Until Phases 2-4 land, the system still functionally answers Pokémon
questions** — the sections below describing tools, prompts, and the UI
reflect that current, pre-migration state. The architecture sections
(agent loop, hybrid retrieval) describe the domain-agnostic core that
carries forward unchanged.

## Highlights

- **Self-designed agent loop** — Plan → Act → Reflect → Answer, hand-built (no LangChain), with autonomous tool selection, self-correction, and (as of Phase 1) a genuinely LLM-driven continue/stop/retry decision at every step.
- **Cross-lingual hybrid retrieval** — a Chinese conversational query scores **0% effective recall with BM25-only → 100% with hybrid (BM25 + vector kNN)** against an English-source corpus.
- **Bilingual, streaming, full-stack** — SSE streaming with a visible reasoning chain; auto language detection; shipped end-to-end (FastAPI + React + ES + PostgreSQL + Docker).
- **Architecture-reuse migration in progress** — same codebase, two domains. See migration status above.

## Features (current — Pokemon domain, pre-Phase-2)

- **Autonomous Agent Pipeline** — Plan → Act → Reflect → Answer; no manual tool selection needed; the Reflect stage loops until the LLM itself judges the answer complete (Phase 1).
- **Three Tools**
  - `rag_search` — Smogon strategy articles (ES hybrid search: BM25 + vector kNN)
  - `pokeapi_query` — Real-time Pokémon data: base stats, learnsets, type matchups (PokeAPI)
  - `web_search` — Latest meta / season rankings (Serper API)
- **Streaming Output** — SSE streaming with visible agent reasoning chain (qwq-plus thinking tokens).
- **Multi-turn Conversation** — Session-scoped history; each new session starts fresh.
- **Bilingual** — Auto-detects input language; responds in Chinese or English; UI supports 中/EN toggle.
- **File Upload & Management** — Upload `.txt` / `.md` strategy docs (indexed into ES); view and delete via the Docs page.

## Tech Stack

| Layer | Technology | Role |
|---|---|---|
| LLM | Qwen — qwq-plus (final answer), qwen-plus (plan/reflection) via DashScope | Reasoning + tool decisions |
| Agent Framework | Custom Plan→Act→Reflect→Answer pipeline (no LangChain) | Tool orchestration + self-correction |
| Knowledge Base | Elasticsearch (Smogon chunks + user uploads, pre-migration) | Hybrid retrieval (BM25 + vector) |
| Real-time Data | PokeAPI REST (pre-migration — Phase 2 replaces with finance data) | Stats / learnsets / type matchups |
| Web Search | Serper API | Latest meta / fallback |
| Backend | FastAPI + PostgreSQL | API, SSE, sessions & messages |
| Frontend | React + TypeScript + Vite + Ant Design + Valtio | Chat UI, streaming render, doc mgmt |
| Infrastructure | Docker Compose (ES + PG) | Local dependencies |

## Agent Pipeline

```
User question
      ↓
  agent_plan()         ── LLM decides which tools to call, breaks into sub-questions
      ↓
  process_actions()    ── calls rag_search / pokeapi_query / web_search; tool errors
      ↓                    are now surfaced to the LLM, not swallowed (Phase 1)
  should_continue()     ── LOOPS: LLM judges if info is sufficient; if not, decides what
      ↓  (bounded loop)    to call next — the loop body, not the LLM, only caps runaway
      ↓                    iterations as a safety net
  final_answer()        ── qwq-plus streams reasoning + answer via SSE
      ↓
  Frontend renders thinking chain + final answer
```

**Tool selection rules (current — Pokemon domain):**
- Base stats / learnsets / type matchups → `pokeapi_query`
- Strategy / team building / item recommendations → `rag_search`
- Latest meta / season data / obscure Pokémon → `web_search`
- Off-topic questions (non-Pokémon) → rejected

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

### 3. Index Smogon Data (current Pokemon-domain corpus, pre-Phase-2)
```bash
python legacy/index_smogon.py
```

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
│       │   ├── chat_rt.py           # /chat SSE, /upload_files, /get_files, /delete_file
│       │   └── history_rt.py        # /sessions, /messages
│       ├── service/
│       │   ├── agent/agent.py       # Agent pipeline (Plan→Act→Reflect→Answer, Phase 1 rework)
│       │   ├── pokeapi/             # PokeAPI tool (live — Phase 2 replaces with finance data tool)
│       │   ├── web_search/          # Serper web search tool
│       │   └── core/file_parse.py   # .txt/.md chunker + ES indexer
│       ├── schemas/chat.py
│       └── utils/database.py
│   └── tests/
│       └── test_agent_loop.py       # Phase 1 unit tests (should_continue, error propagation)
├── frontend/
│   └── src/
│       ├── i18n.tsx                 # Bilingual text (zh/en) — still Pokemon examples, Phase 4
│       ├── components/
│       │   ├── header-bar/          # Header with 中/EN toggle
│       │   └── sender/              # Input box + file attachment
│       └── pages/
│           ├── chat/                # Chat page with SSE streaming
│           └── repository/          # Document management
├── legacy/                          # Quarantined Pokemon-domain data/scripts (Phase 2 reference only)
│   ├── fetch_pokemon_data.py
│   ├── scrape_smogon.py
│   ├── index_smogon.py
│   ├── index_pokemon.py
│   ├── pokemon-data/                # 1025 PokeAPI species dumps (debug cache, not indexed)
│   └── smogon-data/                 # ~20 curated Smogon strategy articles (the live RAG corpus)
├── docker-compose.yml               # ES + PostgreSQL
└── .env                             # API keys and config
```

## Known Limitations

- **Pokémon name translation** — Chinese names for Pokémon/moves/items are generated by the LLM from English source data (PokeAPI + Smogon are English). Accurate for popular Pokémon but may be wrong for obscure ones; a local Chinese name lookup table would be more reliable. (Moot once Phase 3 retargets prompts to finance.)
- **Smogon coverage** — The KB has strategy articles for ~20 popular Gen 9 Pokémon. For uncovered Pokémon, the agent falls back to `web_search` automatically.
- **File upload format** — Only `.txt` / `.md` (no PDF/Word) for user uploads; Phase 2's ported FinReportRAG parser adds PDF/table-aware parsing specifically for the finance corpus ingestion path.

## Roadmap

1. **Phase 2 — Finance data & tools**: live market-data tool (price/fundamentals/news) replacing PokeAPI; port FinReportRAG's table-aware document parser for financial filings; finance RAG corpus (filings + news + educational content).
2. **Phase 3 — Prompt retargeting**: rewrite plan/reflect/final-answer prompts for finance terminology, preserving the Phase 1 iterative loop structure.
3. **Phase 4 — Frontend re-skin**: UI copy, i18n strings, and example questions updated to finance.
4. **Beyond Phase 4** — the MVP (single-ticker stock/market analysis) is architecturally a foundation for a broader investing research copilot (portfolio-level reasoning, multi-asset comparison), reusing the same tool/RAG layer.

Full plan, acceptance criteria, and architecture decisions: [`.omc/plans/finance-agent-migration-plan.md`](.omc/plans/finance-agent-migration-plan.md).

## License / Attribution

Application and agent code is original; the hybrid retrieval is hand-rolled on native
Elasticsearch (no RAGFlow). Pokémon data (pre-migration corpus, now in `legacy/`) via
[PokeAPI](https://pokeapi.co/); strategy content from [Smogon](https://www.smogon.com/);
LLMs via Alibaba Cloud DashScope.
