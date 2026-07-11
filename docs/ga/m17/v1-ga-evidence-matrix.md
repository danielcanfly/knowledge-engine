# Knowledge OS v1 GA Evidence Matrix

Return to the [GA Evidence Index](../README.md).

This matrix closes the cross-milestone traceability gap. Each capability is backed by implementation,
test, workflow, and immutable merged-PR evidence. The machine-readable source is
`ga-evidence-registry.json`.

## Readiness rule

All 20 rows must be `evidence_complete` with no unresolved gap before M17.7 may begin. This document
does not authorize a GA declaration. Final GA acceptance still requires an independent qualified
operator drill.

| ID | Capability | Owner | State | Remaining gate |
|---|---|---|---|---|
| GA-01 | Immutable intake | M10 | evidence_complete | M17.7 drill |
| GA-02 | Evidence-bound synthesis | M11 | evidence_complete | M17.7 drill |
| GA-03 | Dedupe and contradiction handling | M11 | evidence_complete | M17.7 drill |
| GA-04 | Human review | M11 | evidence_complete | M17.7 drill |
| GA-05 | Source validation | M11 | evidence_complete | M17.7 drill |
| GA-06 | Deterministic candidate build | M11/M13 | evidence_complete | M17.7 drill |
| GA-07 | Runtime evaluation suite | M12 | evidence_complete | M17.7 drill |
| GA-08 | Production request governance | M9 | evidence_complete | M17.7 drill |
| GA-09 | Explicit approval | M9 | evidence_complete | M17.7 drill |
| GA-10 | Production promotion | M9 | evidence_complete | M17.7 drill |
| GA-11 | Citation quality | M12/M14 | evidence_complete | M17.7 drill |
| GA-12 | ACL safety | M14/M16 | evidence_complete | M17.7 drill |
| GA-13 | Observability | M15 | evidence_complete | M17.7 drill |
| GA-14 | Freshness propagation | M15 | evidence_complete | M17.7 drill |
| GA-15 | Idempotent replay | M13/M16 | evidence_complete | M17.7 drill |
| GA-16 | Rollback and restore | M16 | evidence_complete | M17.7 drill |
| GA-17 | Multi-batch operations | M13 | evidence_complete | M17.7 drill |
| GA-18 | Real user-facing query experience | M14 | evidence_complete | M17.7 drill |
| GA-19 | Feedback correction loop | M14/M15 | evidence_complete | M17.7 drill |
| GA-20 | Operator-independent handoff | M17 | evidence_complete | M17.7 drill |

## GA-01 Immutable intake

M10 provides immutable, hash-bound intake and connector closure evidence across local Markdown, HTTPS,
PDF, Git, Drive, media, meeting, and database sources.

## GA-02 Evidence-bound synthesis

M11 synthesis proposals bind provider, model, prompt, source spans, and emitted identities while
remaining proposals rather than canonical truth.

## GA-03 Dedupe and contradiction handling

M11 resolution and closure evidence require deterministic duplicate, contradiction, provenance, and
unsupported-claim handling before review.

## GA-04 Human review

M11 immutable decisions and review-only Source packages separate review authority from canonical
Source mutation.

## GA-05 Source validation

M11 compiler contracts and closure reconciliation fail closed on invalid metadata, provenance,
audience, duplicate identifiers, and incomplete review state.

## GA-06 Deterministic candidate build

Compiler outputs and M13 isolated three-batch acceptance prove exact Source-bound deterministic
candidate identities without treating artifacts as editable truth.

## GA-07 Runtime evaluation suite

M12 retrieval, citation, answer, performance, boundary, and final release gates block incomplete or
regressed candidates.

## GA-08 Production request governance

The M9 committed request pins target and expected-previous identities and remains distinct from
approval and dispatch.

## GA-09 Explicit approval

The M9 approval contract is immutable, operation-bounded, separately reviewed, and independently
validated.

## GA-10 Production promotion

M9 promotion reconciliation and R2 release integration preserve exact request consumption,
preconditions, post-promotion verification, and immutable evidence.

## GA-11 Citation quality

M12 quality metrics and M14 claim-aware citations validate support, target correctness, audience,
source cards, and release-bound identities.

## GA-12 ACL safety

M14 public boundaries and M16 adversarial ACL evaluation prove audience non-broadening from Source
fact through answer and citation.

## GA-13 Observability

M15 defines privacy-safe event contracts, bounded dimensions, deterministic telemetry, health, alerts,
and daily reporting.

## GA-14 Freshness propagation

M15 impact graphs propagate direct and transitive source change effects while blocking cycles,
audience broadening, truncation, and identity drift.

## GA-15 Idempotent replay

M13 lifecycle operations and M16 replay objectives accept only exact payload and identity equivalence,
rejecting stale or divergent replays.

## GA-16 Rollback and restore

M16 covers failed-promotion containment, object restoration, Source/control-plane reconstruction,
recovery objectives, runtime verification, and end-to-end drill closure.

## GA-17 Multi-batch operations

M13 proves three concurrent planned/source-review batches, bounded candidate slots, serialized
production mutation, lifecycle reconstruction, retention, and closeout.

## GA-18 Real user-facing query experience

M14 provides stable JSON and SSE ask interfaces, a standalone page, a blog widget, wiki-first
retrieval, citations, source cards, security controls, and product-level acceptance.

## GA-19 Feedback correction loop

M14 immutable feedback intake and M15 triage produce bounded correction candidates without automatic
Source or production mutation.

## GA-20 Operator-independent handoff

M17 architecture, runbooks, failure atlas, inspection tools, and qualification exercises provide the
repository-native handoff surface required for the independent final drill.

## Gap closure result

The prior gap was the absence of one deterministic cross-milestone proof surface. This matrix and its
registry close that traceability gap. The remaining gate is not an evidence-row gap: it is the required
M17.7 independent operator drill and final GA acceptance.