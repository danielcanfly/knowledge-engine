# M25.10 Formal Closure and Scale Authority Gate

Status: `m25_closed`

## Scope

M25.10 production pointer promotion is already complete and must not be replayed.
This closure step compiles the evidence chain, scale readiness model, SLO/cost
review, reviewer-capacity model, incident runbook and owner decision packet
needed for final M25 closure.

The closure issue is `danielcanfly/knowledge-engine#1177`.

## Frozen Production Identities

- Release ID: `m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043`
- Source SHA: `5250f8422f4fa08c1f3dc84840dc756850817635`
- Foundation SHA: `e53af5833193a644a4d7397b7d466ababb5e1373`
- Admission SHA-256:
  `f5f01d82c7a1a38cf15fc54c890b904c4c015f608e2d25e294f9469f9b1927f2`
- Candidate manifest SHA-256:
  `f8e2a2f4b775e053bed93f3379f2aa6decd62b36e32380de0aff16caf14f18f3`
- Production manifest SHA-256:
  `72bb03e3fa22e453735719ab43898adfd4c7f186f818ed71685efb4fcd87de2b`
- Production pointer SHA-256:
  `4a2cf8cc16d598cc2c6928491cf2c3b926e57e571297c61a8c3ff7a4ae396ff9`
- Promotion workflow run: `30115946458`
- Promotion status: `production_pointer_promoted`

## Evidence Ledger

The machine-readable closure evidence is:

`pilot/m25/m25-10-formal-closure-evidence.json`

Daniel's machine-readable owner decision is:

`pilot/m25/m25-10-owner-decision.json`

The final acceptance artifact is:

`pilot/m25/m25-10-final-acceptance.json`

It records one disposition for every M25.1-M25.10 stage. M25.8 and M25.9
remain recorded with their original blocked readiness-gate statuses and are
treated as superseded by the later exact 156-article M25.10 blog path, not as
silently passed gates.

The admitted M25.10 denominator is:

- 156 source documents;
- 25 series or collections;
- 156 article nodes;
- 4,041 section nodes;
- 4,222 graph nodes;
- 8,525 graph edges;
- 4,197 semantic documents;
- 0 unaccounted sources.

## Scale Readiness

This closure packet distinguishes technical capability from authority.

`bounded_manual` is eligible for Daniel's final decision because the accepted
M25.10 evidence pins the exact 156-article corpus, exact release identities,
Qdrant filtered point count and production pointer digest.

`controlled_batch` requires owner conditions before execution: fixed source
denominator, maximum provider and Cloudflare cost, reviewer throughput and
queue-age SLO, checkpoint/resume proof and rollback drill before serving.

`expanded_batch` is deferred until p95/p99 ingestion and embedding durations,
budget stop enforcement, dead-letter and retry ledgers, independent security
review and exact population authority are available.

`continuous_discovery` remains denied.

## SLO, Cost and Reviewer Capacity

Accepted evidence is enough to prove the bounded M25.10 production pointer
promotion and candidate collection identity. It is not enough to infer expanded
or continuous ingestion capacity.

Synthetic latency and hard-coded zero cost are not production evidence. Daniel
must select a budget stop and reviewer queue-age threshold before any controlled
or expanded batch authority can exist.

## Incident and Rollback

The closure evidence records incident entries for:

- production pointer drift;
- production manifest drift;
- Qdrant authority-filter drift;
- Vault artifact drift;
- ACL or public traffic drift;
- reviewer capacity overload;
- cost-budget breach.

Every incident blocks successor production activation until restoration evidence
and a post-incident decision gate exist.

## Owner Decision

Daniel selected exactly one valid outcome:

`approved_bounded_large_scale_ingestion`

The decision was recorded at `2026-07-27T03:36:26Z` and authorizes M25 formal
closure, independent reconciliation and bounded large-scale ingestion readiness
for the accepted 156-article M25.10 corpus. It does not authorize a new
ingestion workload, Source/Foundation mutation, DNS or Cloudflare Access
mutation, credential mutation, production pointer mutation, public traffic
expansion, semantic/hybrid serving expansion or M26 production answer serving.

## Decision Gate Record

The valid outcomes were:

- `approved_bounded_large_scale_ingestion`
- `approved_with_conditions`
- `governed_defer`
- `rejected_pending_redesign`

No default outcome was inferred from this PR. M25 is sealed only because Daniel
recorded the exact owner decision above.

## Protected Boundaries

This closure step does not mutate:

- Source or Foundation;
- release or production pointer;
- R2 production objects;
- Qdrant;
- Worker, Pages, DNS or Access;
- credentials;
- public traffic;
- semantic/hybrid production serving;
- production answer serving.

## M26 Implication

Current `main` includes M26.9-M26.11 forward commits. M26.11 starts a
production-activation contract chain, but it still denies live provider calls,
verified final answers, public traffic and production pointer mutation. M25
formal closure remains separately required for stages that require an
`m25_closed` predecessor.
