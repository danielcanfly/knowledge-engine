# M21.6 reviewer-ready evidence and bulk Source PR preparation

## Status

Implementation contract for issue #328. M21.6 consumes the exact M21.3 extraction packet, exact M21.4 governed candidates, exact M21.5 resolution packet, and a bounded explicit review-item plan. It emits deterministic reviewer-ready item packets and a bulk Source PR preparation manifest. It does not approve any item, write Source, create a GitHub pull request, publish candidate state, or touch production.

## Pinned authority

M21.6 pins:

- Source commit `a6ba738d910d01d2ae99b1968f0831989934c549`;
- Foundation commit `e5ef644053d34e89c70d2ceb37521e1c59234832`;
- the exact Engine, Source, and Foundation identity carried by M21.3 through M21.5;
- the exact M21.4-to-M21.3 and M21.5-to-M21.3/M21.4 packet bindings.

All three upstream packets are validated through canonical JSON SHA-256 before any review material is prepared. Cross-release packet mixing fails closed.

## Entry gate

Packaging is allowed only when M21.5 proves a clean review-preparation boundary:

- `packaging_blocked` is false;
- no contradiction candidate exists;
- no resolution outcome is `probable_duplicate`, `ambiguous`, or `reject`;
- every resolution is pending review and candidate-only;
- every candidate belongs to exactly one resolution record;
- all evidence spans, audience values, Source identity, and Foundation identity remain exact.

M21.6 cannot use confidence, shared tags, relation neighbourhoods, lexical similarity, or batch size to override an M21.5 blocker.

## Explicit review-item plan

The caller supplies one review item for every eligible M21.5 resolution. Each item must bind exactly one resolution and exactly the same sorted candidate IDs. The item declares one bounded action:

- `create_concept`;
- `update_concept`;
- `attach_alias`;
- `add_claim`;
- `add_definition`;
- `add_term`;
- `add_tag`;
- `add_relationship`.

The action must agree with the M21.5 outcome. New concepts may only use `distinct_new_candidate`; alias attachment may only use `attach_alias_candidate`; updates may only use `exact_existing_match`.

## Reviewer packet contents

Every item emits `knowledge-engine-human-review-item/v1` with:

- exact resolution and candidate IDs;
- action and exact Source paths that would change;
- proposed concept body or proposed change;
- exact M21.5 evidence spans;
- selected governed tag candidates;
- selected typed relationship candidates;
- existing concept comparison;
- duplicate, ambiguity, contradiction, and ACL conflict analysis;
- effective audience;
- confidence no greater than M21.5;
- pending-human-review state;
- explicit false authority flags for approval, Source write, GitHub PR creation, canonical knowledge, and production.

Item-level evidence remains visible. The bulk manifest stores exact item packet IDs and hashes rather than replacing the item evidence with a batch summary.

## Source path safety

Prepared paths are relative, normalized, bounded, and limited to canonical Source review surfaces:

- `bundle/concepts/`;
- `provenance/`;
- `registry/`;
- `reviews/`.

Absolute paths, traversal, duplicate paths inside one item, unsupported file types, and cross-item path ownership collisions fail closed. Existing-target operations must include the exact M21.5 concept path. Alias attachment may target only that exact path.

## Governed metadata binding

Selected governed tag candidates must reference at least one candidate in the item. Selected typed relationships must have at least one endpoint in the item. Unknown, duplicate, unrelated, authority-drifted, or evidence-free governed references fail closed.

M21.6 does not infer new tags or relationships and does not materialize inverse edges.

## Conflict and ACL handling

Each item carries an explicit analysis object. Any true duplicate, ambiguity, contradiction, or ACL conflict blocks the entire preparation. The item audience must equal the M21.5 resolution audience; audience broadening or substitution is rejected.

## Output contracts

The item packets are wrapped by `knowledge-engine-human-review-packets/v1`. The bundle binds:

- Source and Foundation SHAs;
- exact Engine identity;
- M21.3 extraction packet SHA-256;
- M21.4 governed packet SHA-256;
- M21.5 resolution packet SHA-256;
- exact item count and deterministic sorted item packets.

The bulk output is `knowledge-engine-bulk-source-pr-preparation/v1`. It includes exact item references, action summaries, target paths, target-file count, and reviewer instructions.

Both outputs state:

- human review required;
- approval not granted;
- Source write not permitted;
- GitHub PR creation not permitted;
- canonical knowledge false;
- production authority false.

## Determinism and bounds

Initial bounds are:

- 1,000 M21.3 candidates;
- 1,000 M21.5 resolutions;
- 1,000 review items;
- eight Source paths per item;
- 64 governed tag or relationship references per item;
- 20,000 normalized characters per proposed body or change;
- 16 exact evidence spans per upstream record.

Canonical JSON, stable item ordering, stable path ordering, exact packet hashes, and packet-bound IDs make replay byte-identical.

## Fail-closed cases

M21.6 rejects:

- upstream packet digest, authority, coverage, or identity drift;
- cross-release M21.3/M21.4/M21.5 combinations;
- M21.5 packaging blockers or contradictions;
- duplicate resolution or candidate ownership;
- incomplete review-item coverage;
- malformed or missing evidence;
- unsupported actions or action/outcome mismatch;
- missing proposed body or change;
- unsafe, ambiguous, or colliding Source paths;
- existing-target comparison drift;
- governed tag or relationship reference drift;
- confidence escalation;
- audience mismatch or ACL conflict;
- secret-like or unbounded content.

## Exclusions

No Source write, Source checkout mutation, GitHub Source PR creation, reviewer decision, canonical adoption, model/provider/network call, live connector, scheduler, queue, worker, candidate publication, production publication, production pointer, retained R2 object, credentials, permanent ledger, rollback, M21.7 or later work, M22 work, cross-release merge, or Graph Neural Retrieval is included.
