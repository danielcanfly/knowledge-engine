# M11 Compiler State Machine and Identities

## 1. State machine

```text
discovered_input
→ admitted
→ structured
→ extracted
→ resolved
→ synthesized
→ validated
→ review_ready
```

Typed terminal alternatives:

```text
rejected_input
rejected_policy
rejected_unsupported
pending_conflict_review
pending_security_review
validation_failed
```

M11.2 ends at `extracted` with a terminal `review_only_complete` result because resolution and synthesis are intentionally out of scope for that reference slice.

## 2. Transition rules

| From | To | Required evidence |
|---|---|---|
| `discovered_input` | `admitted` | exact snapshot, derivative, admission, hashes, connector and policy identity |
| `admitted` | `structured` | deterministic blocks and exact source map |
| `structured` | `extracted` | bounded evidence-bound candidates |
| `extracted` | `resolved` | exact Source snapshot and one outcome per candidate |
| `resolved` | `synthesized` | only eligible resolutions, no unsupported claims |
| `synthesized` | `validated` | complete schema, provenance, policy and safety report |
| `validated` | `review_ready` | immutable reviewer packet and manifest |

Transitions are adjacent. A later stage cannot be asserted without all earlier immutable artifacts. Retrying an already completed transition with identical input returns the existing artifact identity and `idempotent: true`.

## 3. Terminal-state rules

- Identity, hash, schema, admission, or namespace failure ends in `rejected_input`.
- Unresolved or broadened ACL/license ends in `rejected_policy` or `pending_security_review` according to whether the evidence is invalid or needs human policy review.
- A claim without exact evidence ends in `rejected_unsupported` and cannot enter a synthesis proposal.
- Contradiction, ambiguous duplicate, or unsafe merge ends in `pending_conflict_review`.
- Any incomplete provenance chain, unsafe target path, orphan proposal, or contract drift ends in `validation_failed`.
- No terminal state authorizes canonical or production writes.

## 4. Event chain

Every accepted transition emits an immutable event containing:

```text
schema_version
compiler_run_id
ordinal
from_state
to_state
event_at
input_artifact_refs
output_artifact_refs
previous_event_hash
event_hash
mutations_performed
```

`event_hash` is SHA-256 over canonical event content excluding `event_hash`. `mutations_performed` lists only compiler review-object writes and must never contain Source, GitHub governance, candidate, release, production, or permanent-ledger mutations.

## 5. Identity domains

### Evidence identities

M10 owns `source_id`, `snapshot_id`, content hash, derivative ID, and admission identity. M11 references these identities and never rewrites them.

### Run identity

`compiler_run_id` binds:

- exact snapshot and snapshot-object hash;
- exact derivative and derivative-object hash;
- exact admission result and hash;
- effective owner, license, audience, and access policy;
- compiler stage versions and configuration;
- exact canonical Source identity when resolution is requested.

### Artifact identities

Blocks, source maps, candidates, resolutions, proposals, validation reports, and packet manifests are content-addressed within the run. Human review identity is outside the compiler run and references the immutable packet manifest.

## 6. Replay and collision behavior

- Same semantic input and compiler identity: identical run and artifact IDs, identical bytes, idempotent success.
- Same run ID with different bytes: immutable collision, hard failure.
- Same snapshot with a different derivative or compiler version: new run ID.
- Same evidence with different ACL, license, or access policy: new snapshot or run identity and no cross-policy artifact reuse.
- A failed run cannot be overwritten by a successful retry. The retry either reuses identical immutable evidence or receives a new identity.

## 7. Source snapshot identity

Resolution requires an exact clean canonical Source checkout and a deterministic Source snapshot digest. The digest includes tracked relevant Source paths and hashes, repository identity, and exact commit SHA. Dirty worktrees, mutable refs, symlinks, missing registries, or hash drift fail closed.

## 8. Non-identity metadata

Operational telemetry may record actor, execution host, wall time, retry count, and logs, but those fields do not alter semantic artifact identity unless explicitly required by a versioned schema. This prevents harmless operational variation from changing compiler output IDs.