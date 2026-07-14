# M21.7 Phase D acceptance and closure

## Status

Implementation contract for issue #331. M21.7 validates the exact M21.1 through M21.6 completion chain and produces deterministic, evidence-only Phase D acceptance. It does not execute ingestion, review, Source writes, GitHub Source PR creation, publication, or production operations.

## Pinned authority

M21.7 pins:

- Engine baseline `8ae7eae22f591ccd2543af08c82b885b8c703d4c`;
- Source commit `a6ba738d910d01d2ae99b1968f0831989934c549`;
- Foundation commit `e5ef644053d34e89c70d2ceb37521e1c59234832`;
- exact issue, implementation PR, reconciliation PR, head, and merge evidence for M21.1 through M21.6;
- exact-head workflow evidence for all six M21 workflow families and repository regressions.

Narrative milestone labels are not acceptance evidence. Missing or malformed evidence fails closed.

## Milestone evidence

The input schema is `knowledge-engine-phase-d-evidence/v1`. The `milestones` object must contain exactly M21.1 through M21.6. Each milestone records:

- a distinct issue number;
- a distinct implementation PR number;
- a distinct reconciliation PR number;
- completed issue state;
- implementation merged;
- reconciliation merged;
- exact implementation head SHA;
- exact implementation merge SHA;
- exact reconciliation head SHA;
- exact reconciliation merge SHA.

M21.7 does not infer completion from a file, title, or branch name.

## Exact-head workflows

The workflow evidence list must include successful runs for:

- M21.1 Blog Inventory;
- M21.2 Resumable Batch;
- M21.3 Extraction Candidates;
- M21.4 Governed Relations and Tags;
- M21.5 Entity Resolution and Contradictions;
- M21.6 Review Packets and Source PR Preparation;
- CI;
- M17 Architecture Canon Acceptance;
- M18 Graph v2 acceptance;
- R2 Release Integration.

Every workflow entry must bind to the exact Engine head being accepted. A green run on an older head is rejected.

## Throughput bounds

Phase D acceptance requires positive, bounded evidence for:

- inventory items, at most 100,000;
- largest batch, at most 1,000 items;
- human-review items, at most 1,000;
- total output, at most 64 MiB;
- bounded inventory processing;
- bounded batch size;
- bounded reviewer packets;
- bounded output bytes;
- no unbounded queue.

These values are acceptance evidence, not a scheduler or worker implementation.

## Interruption and replay

The replay evidence must prove:

- interruption and resume were exercised;
- replay is deterministic;
- outputs are byte-identical;
- identical inputs produce the same output identity;
- cross-release packet mixing is rejected.

Replay evidence cannot authorize mutation or reuse stale green workflows.

## Privacy and secret safety

Acceptance requires proof that:

- secret scans passed;
- audience and ACL identity were preserved;
- raw private content is absent from review and acceptance artifacts;
- diagnostics remain bounded and privacy safe;
- credentials are absent.

The acceptance report contains indicator booleans and bounded metrics, not secret values, private excerpts, or attack payloads.

## Human-review enforcement

Acceptance requires proof that:

- every item remains individually reviewable;
- review-item coverage is complete;
- ambiguity blocks packaging;
- contradictions block packaging;
- automatic approval is forbidden;
- the bulk manifest preserves exact item packet hashes.

Bulk preparation cannot replace item-level evidence or grant approval.

## Protected boundaries

The following must all be false:

- Source mutation dispatched;
- production mutation dispatched;
- production pointer updated;
- retained R2 state created;
- credentials modified;
- permanent ledger written;
- rollback dispatched;
- Source write permitted;
- GitHub Source PR creation permitted;
- production authority.

## Output

Successful validation emits `knowledge-engine-phase-d-acceptance/v1` with exact identities, milestone and workflow counts, bounded throughput metrics, ordered verified guarantees, `production_authority: false`, and `accepted: true`.

## M21 closure criterion

M21 can close only after:

1. M21.1 through M21.6 implementation and reconciliation evidence is complete;
2. M21.7 implementation and reconciliation are independently merged by expected head SHA;
3. all required exact-head workflows are green;
4. M21.1 through M21.7 issue, PR, CI, merge, and reconciliation evidence is audited against live GitHub state;
5. no protected boundary was mutated;
6. M22 has not started.

## Exclusions

No Source write, Source checkout mutation, GitHub Source PR creation, reviewer decision, canonical adoption, model/provider/network call, live connector, scheduler, queue, worker, candidate publication, production publication, production pointer, retained R2 object, credentials, permanent ledger, rollback, M22 work, cross-release merge, or Graph Neural Retrieval is included.
