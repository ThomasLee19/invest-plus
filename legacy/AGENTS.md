<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-01 -->

# legacy

## Purpose
Quarantined Pokemon-domain data, scripts, and the PokeAPI tool's source
corpus, set aside during the Invest+ rebrand so the top-level project tree
reads as a coherent finance product rather than a half-renamed Pokemon
project. **Nothing here was deleted** — it's preserved for Phase 2 reference
(corpus-fetch pattern, idempotent-indexing pattern) per
[`.omc/plans/finance-agent-migration-plan.md`](../.omc/plans/finance-agent-migration-plan.md).

This directory used to be split across `scripts/` (pipeline scripts) and
`data/` (corpus content) — merged here since both directories' real content
moved together and the split no longer carries information.

**`backend/app/service/pokeapi/pokeapi_tool.py` is NOT here.** It's still
live code, actively imported by `agent.py` at runtime — it stays in place
until Phase 2 replaces it with a finance data tool. Do not move it.

## Contents
| File | Original location | Description |
|------|-------|-------------|
| `index_smogon.py` | `scripts/index_smogon.py` | Indexes `smogon-data/*.md` into ES `pokemon_kb` with `source_kwd="smogon"`. Idempotent: chunk ids keyed by `xxhash(content + index)`, existing docs skipped. `MAX_CHUNK` was kept in sync with `backend/app/service/core/file_parse.py`. |
| `scrape_smogon.py` | `scripts/scrape_smogon.py` | Day-1 scraper for Smogon strategy articles (needs `playwright` + `playwright install chromium`). |
| `fetch_pokemon_data.py` | `scripts/fetch_pokemon_data.py` | Fetches PokeAPI species data into `pokemon-data/*.md`. Held its own copy of `GEN9_VERSION_GROUPS` — was kept aligned with `pokeapi_tool.py`. |
| `index_pokemon.py` | `scripts/index_pokemon.py` | **Was already deprecated before the rebrand.** PokeAPI data is queried live, not indexed. |
| `pokeapi-tool/` | *(not moved — see note above)* | n/a |
| `smogon-data/` | `data/smogon/` | Manually curated Smogon strategy articles (~20 popular Gen 9 Species). Was the RAG corpus — `index_smogon.py` indexed it into ES `pokemon_kb`. |
| `pokemon-data/` | `data/pokemon/` | Per-Species PokeAPI dumps (`pokemon_NNNN_name.md`, full National Dex, 1025 files). Was a debug cache only — never indexed into ES. |

## For AI Agents

### Working In This Directory
- These scripts are not imported by the live app — they were always standalone,
  run-by-hand pipeline scripts, same as before the move.
- ES auth here is still the hard-coded `("elastic", "infini_rag_flow")` — one of
  the four call sites listed in the root [AGENTS.md](../AGENTS.md).
- If you need to run them for reference (e.g. testing the old indexing flow),
  run from the repo root: `python legacy/index_smogon.py`. The ES index they
  write to (`pokemon_kb`) is unchanged for now — that rename is explicitly
  deferred to Phase 2 of the migration plan, in the same step that re-points
  the index at finance content.
- **For Phase 2 work**: `fetch_pokemon_data.py` and `index_smogon.py` are good
  reference patterns for the new finance corpus fetch/index scripts (idempotent
  chunk IDs via `xxhash`, `GEN9_VERSION_GROUPS`-style scoping pattern), even
  though their actual content (Pokemon data) won't be reused.

### Testing Requirements
No unit tests existed for these before the move either.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
