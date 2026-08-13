# M26 One-Day Final Closure Doctor

## Architecture Map

- Source/ingestion: immutable source records compile through existing compiler/source-promotion paths into OKF-style artifacts, graph v2, lexical index, provenance, and the accepted production answer bundle. KEEP.
- Query admission: `/api/m26/query` is owner-only, backend-token protected, rate-limited, no canonical writes. KEEP.
- Retrieval: production bundle + lexical retrieval + local/remote dense channel + relation-aware evidence strengthening. KEEP.
- Synthesis/review: canonical entrypoint is `knowledge_engine.m26_aq_semantic_contract.run_owner_arbitrary_query`; author -> semantic review -> optional repair -> re-review, bounded at 4 provider calls. KEEP with one SIMPLIFY/REPAIR below.
- Guards/citations: deterministic code verifies evidence IDs, exact quote/span membership, graph endpoint/direction, privacy, citations, schema, and unsupported accepted claims. KEEP.
- Closure/deploy: exact-head Oracle deploy, local/routed health identity, R3 12 product smoke, blackbox and targeted collectors. KEEP, with old lexical authority treated as DISABLE_FROM_CLOSURE when it conflicts with product contract.

## Classification

| Layer/module | Classification | Notes |
| --- | --- | --- |
| `m26_aq_semantic_contract.py` | KEEP | Candidate #2R1 remains the semantic core; no local semantic parser is final authority. |
| `m26_pa7_semantic_closure_runtime.py` | KEEP | Correct 4-call architecture and claim-local semantic review. |
| `m26_ask_api.py` | SIMPLIFY | Web adapter defaulted to 2 provider calls, starving repair/re-review. |
| Retrieval/bundle/graph/provenance loaders | KEEP | Existing compiled production bundle is the safe N+1 seam; no new subsystem today. |
| Old frozen lexical/visible expectations | DISABLE_FROM_CLOSURE | Useful as diagnostics only, not product truth. |
| Historical M20-M25 governance/patch modules | DELETE_LATER | Not worth broad cleanup during closure. |

## Root Cause

Run `31682736408` showed answerable rows (`R3-Q01`, `R3-Q03`, `R3-Q06`, `R3-Q07`, `R3-Q08`, `R3-Q09`) retrieved evidence but abstained after two provider calls. The web adapter created `MiniMaxClient(max_calls=2)`, while the accepted semantic closure contract requires up to four logical calls: author, review, one repair, re-review. When the first semantic review reported visible coverage or one insufficient claim, the repair call hit `LiveGateError`, producing whole-answer safe abstention.

This is a production wiring/budget mismatch, not evidence that Candidate #2R1 is wrong. Genuine safety constraints remain: no unknown evidence IDs, no unsupported accepted claims, no question-as-evidence, no sibling evidence rescue, no prompt-injection leakage, and no graph endpoint/direction mutation.

## Minimal Changes

- Align `/ask` web adapter provider budget with the canonical 4-call semantic closure contract.
- Add a focused regression locking that `run_owner_query_for_web` forwards `max_provider_calls=4`.
- Keep old visible/lexical frozen expectations out of final authority; R3 12 is interpreted as product smoke.

## Final Acceptance Commands

- `python -m py_compile src/knowledge_engine/m26_ask_api.py`
- `ruff check src/knowledge_engine/m26_ask_api.py tests/test_m26_pa7_ask_api.py`
- `pytest tests/test_m26_pa7_ask_api.py tests/test_m26_aq_semantic_closure_runtime.py tests/test_m26_aq_canonical_semantic_contract_convergence.py`
- `pytest`
- architecture lock searches for case-specific branches, test-aware production behavior, deterministic auto-entailment, new synonym/parser tables, and quote-collage publication
- deploy exact final SHA, then run R3 12 live product smoke plus health/identity/routed checks
