# M21.2 resumable batch manifest and idempotent intake planning

## Status

Implementation contract for issue #316. M21.2 turns a validated M21.1 inventory snapshot into deterministic, resumable batch evidence. It does not execute connectors, schedule workers, mutate Source, or publish candidate or production state.

## Input authority

The only accepted input is `knowledge-engine-blog-inventory/v1` with:

- a valid snapshot SHA-256;
- `authority: evidence_only`;
- `canonical_knowledge: false`;
- `production_authority: false`;
- exact Engine, Source, and Foundation identity;
- a non-empty bounded item list.

Any digest, identity, or authority drift fails closed before planning.

## Batch plan

The planner:

- ignores inventory records that are explicitly rejected, blocked, or missing;
- creates `verify` actions for captured items and `capture` actions for other actionable items;
- derives stable item keys from canonical URL, content digest, source kind, locator, and audience;
- sorts actionable records deterministically by canonical URL and item key;
- partitions them into batches of at most 100 items;
- derives each batch ID from inventory digest, batch index, and ordered item keys;
- emits a canonical JSON-compatible plan digest.

The plan declares evidence-only authority and grants no canonical knowledge or production authority.

## Checkpoint contract

The initial checkpoint contains exactly one state for every planned item. Supported states are:

- `pending`;
- `running`;
- `completed`;
- `retryable`;
- `failed`;
- `skipped`.

Allowed transitions are intentionally narrow:

- pending to running or skipped;
- running to completed, retryable, or failed;
- retryable to running or failed;
- terminal states do not transition.

Repeating the same terminal transition is idempotent and returns the existing checkpoint unchanged.

## Resume and concurrency

Every checkpoint carries:

- exact plan digest and identity;
- optimistic integer revision;
- per-item batch ID, state, attempt count, failure code, retry time, and update time;
- deterministic resume cursor;
- checkpoint digest.

A write must provide the expected current revision. Stale revisions, tampered digests, missing or extra state rows, duplicate item keys, cross-plan checkpoints, invalid transitions, and attempts beyond eight fail closed.

The resume cursor points to the first pending or retryable item in canonical state order. Completed work is never moved back into the actionable prefix.

## Retry evidence

M21.2 records bounded retry evidence only. A retryable item requires:

- a bounded failure code;
- an exact UTC-normalisable retry time;
- an attempt count no greater than eight.

No timer, queue, worker allocation, backoff execution, or network call exists in this milestone.

## Acceptance

Acceptance covers:

- deterministic partitioning and stable IDs;
- input-order independence;
- rejected and unavailable filtering;
- complete initial checkpoint coverage;
- idempotent completion;
- monotonic resume cursor behaviour;
- retry evidence;
- stale revision and invalid transition rejection;
- inventory, plan, and checkpoint tamper rejection;
- cross-plan and state coverage rejection;
- batch-size and actionable-item bounds;
- M20 and M21.1 regressions.

## Exclusions

No live connector call, crawl, scheduler, queue, worker, Source edit, concept/entity/relation extraction, candidate or production publication, production pointer, retained R2 object, credentials, permanent ledger, rollback, M21.3 work, cross-release merge, or Graph Neural Retrieval is included.
