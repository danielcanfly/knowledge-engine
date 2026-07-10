# End-to-End Governed Batch Runbook

Return to the [Operator Runbook Index](../README.md).

This runbook moves one governed batch from raw evidence to a verified, closed production batch. It
does not authorize any mutation. The machine-readable source of the exact sequence is
`runbook-registry.json`.

## Before starting

Prepare a clean Engine checkout, an exact canonical Source checkout, the applicable Foundation
identity, object-store configuration supplied by the approved environment, and a unique batch
identity. Confirm that permanent ledger issue `#30` remains open. Do not copy old production
identities into a new request.

Create a working evidence directory outside canonical Source. Each stage gets its own subdirectory.
Never place provider output, raw private text, credentials, or temporary review material into the
Source tree.

## Canonical sequence

### 1. Preflight

Record operator intent, scope, exact repository identities, intended audience, current production
identity, rollback target, and the checks required before any later mutation. Confirm the universal
stop conditions in the architecture canon.

**Advance only when:** every required identity is present and the operator can explain the Source,
candidate, production, and evidence boundaries.

### 2. Intake

Run `knowledge-intake` with an explicit source identity, locator, title, kind, audience, retrieval
time, owner, and license. The output is immutable capture evidence and a review packet. Intake never
writes canonical Source.

**Stop when:** secret-like material is detected, access policy is unresolved, prompt-injection
evidence requires security review, or the capture identity cannot be reproduced.

### 3. Synthesis preparation

Run `knowledge-synthesis prepare` against the exact capture. Pin provider, model, model version,
prompt version, harness version, seed, temperature, actor, and UTC request time.

**Advance only when:** the request envelope is complete, provider-neutral, evidence-bound, and
identified by its emitted request identity.

### 4. Synthesis validation

Supply strict model JSON to `knowledge-synthesis validate`. Unsupported claims, invalid spans,
identity mismatch, or malformed output block the batch. Generated prose remains a proposal.

### 5. Resolution

Run `knowledge-resolution` against the exact canonical Source checkout and Source SHA. Preserve
deduplication, contradiction, audience, provenance, and requested-action evidence.

### 6. Human review

A named reviewer records `approved`, `rejected`, or `needs_changes` using `knowledge-review decide`.
Approval must cover the exact resolution identity and may keep or restrict audience, never broaden
it. Rejected or needs-changes work does not advance.

### 7. Source package

Use `knowledge-review package` only after an approved immutable decision. The package is a bounded
proposal against an exact Source SHA. It is not a Source commit and has no GitHub write authority.

### 8. Source PR

Open a Source pull request from the reviewed package. Recheck the expected Source head immediately
before merge. Merge only after Source validation and explicit human approval. A stale base, package
drift, incomplete review coverage, quarantine, or audience broadening blocks the merge.

The resulting Source commit SHA is the only canonical knowledge identity consumed downstream.

### 9. Source validation

Validate the exact Source commit. The compiler must reject missing metadata, unapproved concepts,
duplicate identifiers, broken internal links, unsafe paths, missing provenance, and invalid
audience.

### 10. Candidate build

Publish only to a candidate channel using the exact Source, Engine/Builder, and Foundation
identities. Candidate publication is a governed object-store mutation. It requires a unique
operation identity, explicit bounded approval, exact expected previous candidate state, and a ready
cleanup or supersession plan.

### 11. Candidate acceptance

Run the candidate gate and required quality workflows. Verify runtime load, manifest and artifact
digests, public query behavior, citations, ACL-negative behavior, regression floors, and release
identity. Production must remain unchanged.

### 12. Promotion request

Commit a request under `production_promotions/` that pins the candidate release, manifest, Source,
Builder, Foundation, operation ID, expected previous production identity, actor, reason, public
acceptance query, expected citation, and optional ACL-negative check. Runtime supplies the
control-plane SHA; the committed request must not.

### 13. Production approval

Review the exact committed request and evidence. Approval must be explicit, bounded to one operation,
and include verification and rollback readiness. Approval text or issue state cannot substitute for
the immutable approval evidence required by the workflow.

### 14. Production promotion

Dispatch only the governed production workflow with the committed `request_path`. The workflow
revalidates the request, expected previous production state, candidate identity, approval, and
environment before the atomic pointer mutation. Never edit the production pointer directly.

### 15. Runtime verification

Verify the active production release and manifest, then run the public query, citation checks,
ACL-negative check, cache binding, and health checks named in the request. Failed verification
enters the governed rollback or incident path. It never becomes an optimistic pass.

### 16. Permanent ledger evidence

Only the promotion workflow's verified ledger renderer may append the bounded production evidence
entry to issue `#30`. The ledger is evidence, not approval, and must remain open.

### 17. Batch closeout

Run `knowledge-m13 closeout` with the exact batch identity, expected registry and batch versions, and
the verified ledger reference. Closeout is an adjacent lifecycle mutation. Stale versions,
incomplete evidence, or production identity mismatch block it.

### 18. Final reconciliation

Run the M13 integrity audit and operator status checks. Confirm the batch is closed, production
matches the promoted target, no candidate lease or permit remains live, ledger continuity is intact,
and no orphaned or contradictory lifecycle state exists.

## Completion definition

The batch is complete only when final reconciliation passes and all exact identities can be traced
from raw capture through review, canonical Source, candidate release, approved promotion,
production verification, ledger evidence, and closeout. A successful promotion without closeout is
not a completed batch.
