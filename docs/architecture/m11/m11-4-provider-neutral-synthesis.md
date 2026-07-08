# M11.4 Provider-Neutral Evidence-Bound Synthesis Proposals

Status: implementation candidate
Parent milestone: #146
Slice issue: #153
Engine baseline: `40069b3d90766f7b25a872c0d52422b13ff4e10d`
Canonical Source baseline: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`

## Purpose

M11.4 consumes one exact completed M11.3 resolution batch and converts only explicitly synthesis-eligible outcomes into deterministic reviewer-facing proposal objects. It does not call a model, render a provider-specific prompt, write canonical Source, open a Source pull request, approve content, build a candidate, publish a release, mutate production, or append the permanent audit ledger.

## Eligible outcomes

The mapping is exact:

```text
new_concept             -> concept_create
existing_concept_update -> concept_update
alias                   -> alias_add
supersession            -> supersession_update
```

A resolution must both use an eligible outcome and carry `synthesis_eligible: true`. Duplicate, contradiction, unresolved conflict, rejected unsupported claim, and any explicitly ineligible resolution are preserved in quarantine rather than silently discarded or synthesized.

## Evidence boundary

Before planning proposals, the implementation revalidates:

- the M11.3 resolution record, result, resolution set, source snapshot, candidate index, validation report, and adjacent hash-linked event chain;
- the exact compiler candidate set referenced by the resolution batch;
- unique resolution identities and candidate continuity;
- non-empty evidence references containing the exact candidate identity;
- exact Source snapshot identity and target presence;
- valid audience values and non-broadening policy;
- all canonical, GitHub, and production write permissions remain false.

Each proposal preserves its resolution ID, candidate ID, source-map evidence references, target IDs, Source snapshot digest, effective audience, and deterministic structured payload.

## Provider-neutral payloads

M11.4 emits operations rather than provider text:

- `create_concept_draft`
- `append_evidence_bound_claim`
- `add_alias`
- `mark_superseded`

The request requires `provider: none`. Provider invocation is explicitly forbidden and recorded as zero in validation evidence. A later bounded adapter may render these operations for a model, but no provider output is trusted or canonical in this slice.

## Immutable layout

```text
compiler/v1/proposals/{proposal_batch_id}/proposal-record.json
compiler/v1/proposals/{proposal_batch_id}/proposal-set.json
compiler/v1/proposals/{proposal_batch_id}/claim-map.json
compiler/v1/proposals/{proposal_batch_id}/quarantine.json
compiler/v1/proposals/{proposal_batch_id}/validation-report.json
compiler/v1/proposals/{proposal_batch_id}/events/{ordinal}-{event_sha256}.json
compiler/v1/proposals/{proposal_batch_id}/result.json
compiler/v1/synthesis-rejections/{attempt_id}/evidence.json
compiler/v1/synthesis-rejections/{attempt_id}/result.json
```

The state sequence is:

```text
validated_resolution
-> proposals_planned
-> evidence_bound
-> review_only_complete
```

Identical request and evidence produce identical IDs and bytes. Replays are idempotent. Same-key byte mismatches are immutable collisions and fail hard.

## Production invariant

Production remains byte-for-byte unchanged:

- release: `20260708T040116Z-69a9f445699a`
- manifest SHA-256: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- pointer SHA-256: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

Issue #30 remains open and receives no entry because no production mutation occurs.
