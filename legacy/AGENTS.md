<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-01 -->

# legacy

## Purpose
Quarantined Pokemon-domain data, scripts, and the PokeAPI tool's source
corpus, set aside during the Invest+ rebrand so the top-level project tree
reads as a coherent finance product rather than a half-renamed Pokemon
project. Originally nothing here was deleted, preserved for Phase 2 reference
(corpus-fetch pattern, idempotent-indexing pattern) per
[`.omc/plans/finance-agent-migration-plan.md`](../.omc/plans/finance-agent-migration-plan.md).
Now that the finance migration (including `scripts/index_finance.py`, which
reused this directory's indexing pattern) is done, `index_smogon.py` has
been removed as confirmed-unused Pokemon-project leftover code.

This directory used to be split across `scripts/` (pipeline scripts) and
`data/` (corpus content) — merged here since both directories' real content
moved together and the split no longer carries information.

**`backend/app/service/pokeapi/pokeapi_tool.py` is NOT here.** It's still
live code, actively imported by `agent.py` at runtime — it stays in place
until Phase 2 replaces it with a finance data tool. Do not move it.

## Contents
| File | Original location | Description |
|------|-------|-------------|
| `index_smogon.py` *(removed)* | `scripts/index_smogon.py` | **Deleted** — was unused Pokemon-project leftover code superseded by `scripts/index_finance.py`. Indexed `smogon-data/*.md` into ES `pokemon_kb` with `source_kwd="smogon"`; idempotent chunk ids keyed by `xxhash(content + index)`. |
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
- `index_smogon.py` has been deleted (confirmed unused, no importers anywhere
  in the repo). Its indexing pattern (idempotent chunk IDs via `xxhash`, ES
  auth centralized via env vars rather than hardcoded) was already reused by
  `scripts/index_finance.py`, which is what the live app uses now — the ES
  index is `finance_kb`, not `pokemon_kb`.
- The remaining scripts here (`scrape_smogon.py`, `fetch_pokemon_data.py`,
  `index_pokemon.py`) are untouched; if you need to run one for reference,
  run from the repo root, e.g. `python legacy/fetch_pokemon_data.py`.

### Testing Requirements
No unit tests existed for these before the move either.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
