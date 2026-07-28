# M26.PA.4 Attempt-2 Independent Reconciliation

Status: `m26_pa_4_verified_answer_citation_gate_accepted`

This reconciliation accepts M26.PA.4 only as the bounded MiniMax M3 verified-answer and
citation gate that was repaired by PR #1209, merged with expected-head protection, and
executed once on `main`. It is effective only after this independent reconciliation branch
merges.

## Accepted Evidence

- Dedicated reconciliation issue: `#1210`
- Repair issue: `#1208`
- Repair PR: `#1209`
- Repair base: `7a3399d0b1033dbe982a966fa1c4d693f27cda37`
- Repair head: `0ee8c75e87434a33c64b37bd5a2837c2dad10ef8`
- Repair merge: `96a5497f65aee27f8b13a017484be67824ea4160`
- Trigger marker: `[m26.pa4-real-verified-answer-authorized-attempt-2]`
- Workflow: `M26.PA.4 Real Verified Answer and Citation Gate`
- Run ID: `30386218699`
- Run number: `9`
- Run attempt: `1`
- Live job: `90366074535`
- Evidence artifact: `8699066827`
- Artifact name: `m26-pa-4-live-verified-answer-evidence-attempt-2`
- Artifact archive digest:
  `sha256:aafafd31c617b705e002591717b1dfbbb7a70a3a96e20d52cbcd52bae9766df9`
- Receipt file SHA-256:
  `e48fb52fc048f5fc875ca3d265acd4af05f4c5ec2f16f61f586c4c53c2c15565`
- Receipt self SHA-256:
  `7eec05e7d18b1c3c521379c6bb341f0827ef54dbc2df49337d0a24fe3678fd6a`
- Frozen benchmark population digest:
  `f0a2bc69ea76fba5387050d0a2a25309ec4db86d94203d6f6eb21da9e305fe5b`
- Policy digest:
  `56d7743ded108309fefbbeede2ed2eb6e5ae295540c41f458ab5ec5a2fad6069`

## Attempt-1 And Supersession

Attempt 1 remains immutable failed evidence and must not be rerun:

- Run ID: `30373895685`
- Run attempt: `1`
- Head SHA: `7a3399d0b1033dbe982a966fa1c4d693f27cda37`
- Failure code: `M26-PA4-068`
- Ready candidates: `0`
- Abstentions: `12`
- Receipt file SHA-256:
  `71b2056961a50063f21a30ac4dabe8317650e564d895d027565f9734a67e57f7`

PR #1207 is retained only as a superseded failed-repair record. Its
`minimum_ready_candidate_items = 0` threshold was not adopted.

## Receipt Summary

The verified receipt records:

- provider: `minimax`
- model: `MiniMax-M3`
- credential name: `MINIMAX_API_KEY`
- environment: `m23-r3-diagnostic`
- benchmark population count: `12`
- candidate-eligible count: `10`
- mandatory abstention count: `2`
- ready candidates: `8`
- abstentions: `4`
- material claims: `8`
- supported material claims: `8`
- unsupported material claims: `0`
- citation precision: `1.0`
- all non-abstained material claims supported: `true`
- provider calls: `12`
- maximum provider calls per item including repair: `2`
- maximum repair attempts: `1`
- input tokens: `8258`
- output tokens: `785`
- total tokens: `9043`

The aggregate sanitized reason-code diagnostics are:

- `CASE_POLICY_REQUIRES_ABSTENTION`: `2`
- `EXACT_SPAN_MATCH`: `8`
- `INSUFFICIENT_SUPPORT`: `3`
- `INSUFFICIENT_TEMPORAL_FRESHNESS`: `1`
- `TEMPORAL_FRESHNESS_UNVERIFIED`: `1`

## Privacy And Mutability Boundary

The receipt and this acceptance artifact preserve only sanitized diagnostics, hashes, counts,
and bounded operational metadata. They do not persist raw provider response text, raw corpus
text, complete prompts, user queries, answer text, secret values, or vectors.

The run performed only bounded reads of the frozen R2/Qdrant evidence surface. It records:

- R2 reads: `3`
- Qdrant count operations: `1`
- Qdrant scroll operations: `17`
- R2 writes: `0`
- Qdrant writes: `0`
- canonical writes: `0`
- production pointer mutations: `0`
- public shadow/canary traffic operations: `0`
- Source/Foundation/release mutations: `0`

PA.4 acceptance does not authorize another live provider call, PA.5 execution, PA.6 canary
traffic, PA.7 final authority, production answer serving, production pointer mutation,
public traffic, canonical writes, raw text persistence, secret persistence, vector
persistence, or `m26_closed`.

PA.5 may begin only after this reconciliation merges and only through a fresh issue, fresh
branch, implementation PR, exact-head CI, expected-head merge, independent reconciliation,
and Daniel's explicit PA.5 hard-gate approval for the exact controlled internal pilot
envelope.
