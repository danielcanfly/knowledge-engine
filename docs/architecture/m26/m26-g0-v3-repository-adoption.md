# M26.G0 v3 Repository Adoption

Issue: `#1178`  
Base main: `4d7e661a21397ba5c88ba7160f3d0be3bd45cee3`  
Unified M26 v3 SHA-256: `6e71ca5981e3eb45987d188c9c7fb2851a4b5f31803655dd2fc7e28ed4bd22a9`  
G0 stage package SHA-256: `65a2e6ae16837c66acf9b79d7f5ffa7e9b4e082d0d2e268ebf508630ef12407a`

## Purpose

M26.G0 adopts Unified M26 v3 as the sole repository-governed M26 specification without
rewriting historical Git artifacts. It establishes the canonical milestone aliases,
stage registry, dependency DAG, PA.1 historical ratification contract, and the preserved
PA.5 and PA.7 obligations.

## Canonical reconciliation

| Historical label | Canonical v3 stage | Treatment |
|---|---|---|
| M26.9 | M26.S9 | Synthetic QA preflight, not the controlled pilot |
| M26.10 | M26.S10 | Synthetic authority preflight, not final answer authority |
| M26.11 | M26.PA.1 | Historical authority-freeze groundwork ratified by G0 reconciliation |
| M26.12 | M26.PA.2 | Candidate patch only, requiring complete P0/P1 repair |
| M26.13–M26.17 | M26.PA.3–PA.7 | Governed future activation stages |

Historical acceptance statuses are preserved as immutable aliases. No historical acceptance
file is renamed or rewritten.

## Current dependency truth

M25 is formally sealed as `m25_closed` by
`pilot/m25/m25-final-reconciliation.json`, merged on main at
`4d7e661a21397ba5c88ba7160f3d0be3bd45cee3`. This conclusion is derived from the
independent M25 reconciliation, not from production pointer promotion.

The legacy branch `chatgpt/m26-12-real-corpus-binding` remains candidate material only at
head `40061ebf66b057dca490708b7abbaa5988b4edb8`. Against the G0 base it is six commits
ahead and six behind. It has no PR, live run, or acceptance and must not be merged.

## Preserved obligations

PA.5 retains the authenticated internal/shadow pilot with a frozen population of 200–500
questions, multiple reviewers, complete denominator accounting, and quality, security,
latency, cost, and recovery metrics.

PA.7 retains the final evidence-chain compilation, SLO and cost envelope, rollback proof,
Daniel's explicit answer-serving authority outcome, independent reconciliation, and M26
closure.

## Authority boundary

G0 permits governance artifacts, schemas, deterministic validation, tests, documentation,
and read-only repository verification only. It grants no live provider calls, real-corpus
live reads, answer generation, shadow/canary/public traffic, production answer serving,
secret access, or mutation of Source, Foundation, release, R2, Qdrant, Workers, Pages,
DNS, Access, or production pointers.

Implementation merge alone does not accept G0. A separate reconciliation must record both:

- `m26_g0_milestone_reconciliation_accepted`
- `m26_pa_1_production_activation_authority_freeze_accepted`

Only that reconciliation merge unlocks a fresh PA.2 repair branch. PA.2 live execution
still requires Daniel's separate exact read-only live-run approval.
