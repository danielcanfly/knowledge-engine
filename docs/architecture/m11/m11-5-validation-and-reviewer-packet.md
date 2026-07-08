# M11.5 Compiler-Wide Validation and Reviewer Packet

Status: implementation candidate
Parent milestone: #146
Slice issue: #154
Depends on: #153
Engine baseline before this batch: `40069b3d90766f7b25a872c0d52422b13ff4e10d`
Canonical Source baseline: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`

## Purpose

M11.5 consumes one exact completed M11.4 proposal batch, revalidates the complete compiler evidence chain, and emits an immutable reviewer packet. The packet is ready for a human decision but grants no approval or mutation authority.

## Validation boundary

The validator checks:

- proposal record, result, proposal set, claim map, quarantine, validation report, and adjacent synthesis event chain;
- exact revalidation of the underlying M11.3 resolution batch;
- one-to-one proposal-to-resolution identity;
- exact candidate, evidence, target, Source snapshot, and audience continuity;
- exact proposal kind and provider-neutral operation mapping;
- no duplicate proposal or resolution identity;
- no orphan proposal;
- no unsupported, contradictory, unresolved, duplicate, or explicitly ineligible resolution leaking into proposals;
- complete and disjoint coverage across proposals and quarantine;
- no audience broadening;
- no provider invocation and no canonical, GitHub, or production write permission;
- every proposal remains `pending_human_review`.

A malformed or tampered chain produces immutable typed rejection evidence. Partial packets are never emitted.

## Reviewer packet

A successful packet contains:

- summary with proposal, quarantine, and high-risk counts;
- proposal index with structured operations and exact evidence references;
- risk report where supersession is high risk, create/update is medium risk, and alias is low risk;
- quarantine report that remains release-blocking while unresolved items exist;
- review checklist requiring evidence, target, audience, private-data, and explicit approve/reject/change decisions;
- immutable result and hash-linked event chain.

The checklist initializes every decision field to `null`. Automatic approval is always false. Human decision recording and Source PR package generation remain M11.6.

## Immutable layout

```text
compiler/v1/reviewer-packets/{reviewer_packet_id}/packet-record.json
compiler/v1/reviewer-packets/{reviewer_packet_id}/summary.json
compiler/v1/reviewer-packets/{reviewer_packet_id}/proposal-index.json
compiler/v1/reviewer-packets/{reviewer_packet_id}/risk-report.json
compiler/v1/reviewer-packets/{reviewer_packet_id}/quarantine-report.json
compiler/v1/reviewer-packets/{reviewer_packet_id}/review-checklist.json
compiler/v1/reviewer-packets/{reviewer_packet_id}/events/{ordinal}-{event_sha256}.json
compiler/v1/reviewer-packets/{reviewer_packet_id}/result.json
compiler/v1/reviewer-packet-rejections/{attempt_id}/evidence.json
compiler/v1/reviewer-packet-rejections/{attempt_id}/result.json
```

The state sequence is:

```text
validated_proposals
-> risk_assessed
-> review_packet_assembled
-> review_ready
```

IDs and bytes are deterministic. Exact replay is idempotent. Immutable collisions fail hard.

## Mutation boundary

M11.5 does not:

- record a human decision;
- modify canonical Source;
- create or merge a Source pull request;
- create a candidate or release request;
- promote, roll back, or mutate production;
- append issue #30.

The production release, manifest digest, and pointer digest therefore remain unchanged.
