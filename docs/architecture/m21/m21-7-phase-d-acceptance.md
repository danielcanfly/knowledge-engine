# M21.7 Phase D acceptance and closure

## Status

Implementation contract for issue #331, hardened by closure-audit issue #334. M21.7 validates the exact M21.1 through M21.6 completion chain and produces deterministic, evidence-only Phase D acceptance. It does not execute ingestion, review, Source writes, GitHub Source PR creation, publication, or production operations.

## Pinned authority

M21.7 pins:

- Source commit `a6ba738d910d01d2ae99b1968f0831989934c549`;
- Foundation commit `e5ef644053d34e89c70d2ceb37521e1c59234832`;
- exact issue, implementation PR, reconciliation PR, head, and merge evidence for M21.1 through M21.6;
- each milestone-specific workflow to that milestone's accepted implementation head;
- M21.7 and repository-wide regression workflows to the exact final Phase D Engine head.

Narrative milestone labels are not acceptance evidence. Missing, stale, swapped, or malformed evidence fails closed.

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
- exact reconciliation merge SHA;
- its exact governed workflow name;
- successful workflow conclusion;
- workflow head equal to the milestone's implementation head.

M21.7 does not infer completion from a file, title, branch name, or green run on another head.

## Exact-head workflows

Milestone-specific workflow evidence is bound independently:

- M21.1 Blog Inventory → M21.1 implementation head;
- M21.2 Resumable Batch → M21.2 implementation head;
- M21.3 Extraction Candidates → M21.3 implementation head;
- M21.4 Governed Relations and Tags → M21.4 implementation head;
- M21.5 Entity Resolution and Contradictions → M21.5 implementation head;
- M21.6 Review Packets and Source PR Preparation → M21.6 implementation head.

The final workflow list must contain exactly these successful runs on the final Phase D Engine head:

- M21.7 Phase D Acceptance;
- CI;
- M17 Architecture Canon Acceptance;
- M18 Graph v2 acceptance;
- R2 Release Integration.

This split reflects live path-filtered GitHub Actions behavior while preserving exact-head acceptance. A milestone workflow cannot be substituted with another milestone's workflow, and a stale repository regression cannot close Phase D.

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
2. each milestone-specific workflow is green on that milestone's accepted implementation head;
3. M21.7 and repository-wide regression workflows are green on the final Phase D head;
4. M21.7 implementation and reconciliation are independently merged by expected head SHA;
5. M21.1 through M21.7 issue, PR, CI, merge, and reconciliation evidence is audited against live GitHub state;
6. Source and Foundation remain on the exact pinned release SHAs;
7. no protected boundary was mutated;
8. M22 has not started.

## Exclusions

No Source write, Source checkout mutation, GitHub Source PR creation, reviewer decision, canonical adoption, model/provider/network call, live connector, scheduler, queue, worker, candidate publication, production publication, production pointer, retained R2 object, credentials, permanent ledger, rollback, M22 work, cross-release merge, or Graph Neural Retrieval is included.

## Original M21.7 closure reconciliation

M21.7 implementation and acceptance evidence was reconciled against live GitHub state.

- entry Engine main: `8ae7eae22f591ccd2543af08c82b885b8c703d4c`;
- initial implementation head: `f75496d73cf6a04bdda21fc1e1c087d0903c5446`;
- formatting-corrected head: `5e0fda9ab91bec183b836ed2037113900fc84220`;
- accepted implementation head: `84d19d8886f835704f69e62ea98cb585eddd05e7`;
- implementation merge: `2f38edc9974e09c1d281ecbb8858ddfd9799e040`;
- reconciliation head: `2d94f36567630d50d79815abd2fe37729c7c8d68`;
- reconciliation merge: `669e1b0b31cf218e8283004f6828f40955a13eff`;
- issue: #331;
- implementation PR: #332;
- reconciliation PR: #333.

The accepted implementation diff contained exactly the M21.7 workflow, architecture document, validator, and test file. The implementation head passed M21.7 #3, CI #700, M17 #81, M18 #136, and R2 #475. The reconciliation head passed M21.7 #4, CI #702, M17 #82, and M18 #138. Both PRs had clean comment, review, and thread state and were merged by expected head SHA.

## Closure-audit correction

The post-M21.7 live audit found that the original validator required all workflow families to share one final Engine SHA, which did not match path-filtered milestone workflow execution. It also accepted any syntactically valid Source and Foundation SHA.

Issue #334 corrects this by:

- binding M21.1 through M21.6 workflows to their own accepted implementation heads;
- binding M21.7 and repository-wide regressions to the final Phase D head;
- pinning Source and Foundation to the exact governed release SHAs;
- rejecting swapped workflow names, stale workflow heads, duplicate final workflows, and release identity drift.

M21 remains open until issue #334 implementation and reconciliation are complete. Production mutation dispatched: false.
