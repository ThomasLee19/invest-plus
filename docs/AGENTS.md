<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-01 | Updated: 2026-07-01 -->

# docs

## Purpose
Authoritative project documentation: accepted architecture decisions (ADRs) and
agent-workflow conventions (issue tracker, triage labels, domain docs). These are
**source of truth** — check them before contradicting a decision or naming things.

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `adr/` | Architecture Decision Records — accepted, binding decisions |
| `agents/` | Conventions for AI/agent workflows referenced by `CLAUDE.md` |

### adr/
No accepted ADRs yet. When a binding architecture decision is made, add one
here rather than only capturing it in a PR description.

### agents/
| File | Purpose |
|------|---------|
| `domain.md` | Single-context repo convention: one `CONTEXT.md` + `docs/adr/` at the root. |
| `issue-tracker.md` | Issues live in **GitHub Issues** via the `gh` CLI. |
| `triage-labels.md` | Label vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. |

## For AI Agents

### Working In This Directory
- Before contradicting an ADR's decision, read it first — if a change conflicts,
  write a new superseding ADR rather than silently diverging.
- Ubiquitous-language terms live in the repo-root `CONTEXT.md`, not here. Use its
  vocabulary (Ticker / Filing / RAG 知识库 / finance_query / rag_search / web_search).
- ADRs are append-only history: don't rewrite an accepted decision in place.

## Dependencies

### Internal
- Referenced by root `CLAUDE.md`, `AGENTS.md`, and `CONTEXT.md`.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
