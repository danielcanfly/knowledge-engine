# M23.7-R3.1 Independent Reconciliation

## Purpose

This reconciliation independently binds the merged R3.1 diagnosis to its accepted exact-head evidence. It does not reopen the diagnosis, include a repair proposal, change retrieval authority, mutate Qdrant or grant promotion eligibility.

## Accepted diagnosis

- Diagnosis PR: `#482`
- Diagnosis head: `7583aca27d330ff5207c738aff39ab11911a6ccb`
- Diagnosis merge SHA: `41609ef983de09208766fe8c016e9b28526fa3ea`
- R3 receipt SHA-256: `43496be4ff84589c74075124e9f70fc7a2b89f2a400c287ebeb35053b1c6e7fe`
- Operator-result canonical SHA-256: `5a3d950142ae85cc27997326b894ed8cce338918370dcd8ff94474300476dc2a`
- Root-cause report SHA-256: `10a5bd0aa1b141cb508db8781269d2d47ed1cf9309a3065671f3356f7e1d5f7c`
- Reconciliation record SHA-256: `8eb0e46693741d3f66008d3d23ab99570edb9fff3096d5c1c6a2aebb9d6fbb99`

## Exact-head evidence

The diagnosis head passed:

- M23.7 Repair R3.1 Root-Cause Diagnostics, run `29451004955`;
- CI, run `29451004964`;
- M17 Architecture Canon Acceptance, run `29451004973`;
- M18 Graph v2 acceptance, run `29451004966`;
- R2 Release Integration, run `29451005012`.

## Reconciled conclusion

- Primary root cause remains `identifier_humanisation_query_collision`.
- `corpus_hubness` remains a compounding factor.
- No repair proposal is included.
- Production retrieval remains `lexical`.
- Promotion eligibility remains false.
- `blocked_pending_retrieval_quality` remains open.
- Parent issue `#474` remains open.

## Closure rule

Issue `#478` may close only after this reconciliation PR passes exact-head CI and merges with expected-head protection. The next legal workstream is a separately governed repair proposal.
