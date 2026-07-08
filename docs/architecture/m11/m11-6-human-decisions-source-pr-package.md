# M11.6 Immutable Human Decisions and Source PR Package Integration

Status: implementation candidate
Parent milestone: #146
Slice issue: #156
Engine baseline: `2e4bbb445b4762ae9cde191edc121ae82b9914d0`
Canonical Source baseline: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`

## Purpose

M11.6 consumes one exact M11.5 reviewer packet, records explicit human decisions for every proposal, and may generate a deterministic review-only Source PR package for the approved subset. It does not automatically approve content, mutate canonical Source, open or merge a GitHub pull request, build a candidate, publish a release, change production, or append the permanent production ledger.

## Decision contract

Every proposal requires exactly one explicit decision:

```text
approved
rejected
needs_changes
```

An approved decision requires:

- an exact reviewer identity;
- an exact UTC timestamp;
- non-empty global and proposal-level notes;
- an approved audience equal to or more restrictive than the proposal audience;
- explicit high-risk acknowledgement for supersession proposals.

Non-approved decisions cannot set an approved audience or risk acknowledgement. Decisions are immutable and deterministic. A missing proposal decision, duplicate decision, orphan decision, audience downgrade, pre-populated checklist decision, or automatic-approval signal fails closed.

## Package eligibility

A Source PR package is permitted only when:

- at least one proposal is explicitly approved;
- every proposal has an explicit decision;
- no proposal remains `needs_changes`;
- the reviewer packet contains no quarantined resolution;
- all decision and packet evidence chains validate;
- the exact canonical Source checkout is clean and matches the reviewed Source SHA and snapshot.

Rejected proposals remain in the package exclusions report. Quarantined content is never package eligible.

## Review-only Source PR package

The package contains:

- immutable package manifest;
- complete proposal decision set;
- deterministic file plan;
- exclusion report;
- validation report;
- content payloads for bounded non-destructive file changes;
- hash-linked events and terminal result.

Supported plan operations are:

```text
add
replace
verify_no_change
manual_supersession_review
```

Supersession remains a manual review operation. An alias already present in Source becomes `verify_no_change`. Multiple approved proposals attempting to write the same Source path fail closed.

All packages retain:

```text
source_pr_creation_permitted: false
direct_apply_permitted: false
canonical_write_permitted: false
github_write_permitted: false
production_write_permitted: false
```

## Immutable layouts

```text
compiler/v1/review-decisions/{decision_set_id}/decision-record.json
compiler/v1/review-decisions/{decision_set_id}/decisions.json
compiler/v1/review-decisions/{decision_set_id}/validation-report.json
compiler/v1/review-decisions/{decision_set_id}/events/{ordinal}-{event_sha256}.json
compiler/v1/review-decisions/{decision_set_id}/result.json

compiler/v1/source-pr-packages/{package_id}/package-manifest.json
compiler/v1/source-pr-packages/{package_id}/file-plan.json
compiler/v1/source-pr-packages/{package_id}/proposal-decisions.json
compiler/v1/source-pr-packages/{package_id}/exclusions.json
compiler/v1/source-pr-packages/{package_id}/validation-report.json
compiler/v1/source-pr-packages/{package_id}/payloads/*
compiler/v1/source-pr-packages/{package_id}/events/{ordinal}-{event_sha256}.json
compiler/v1/source-pr-packages/{package_id}/result.json
```

Typed rejection evidence is written under separate immutable rejection prefixes. Exact replay is idempotent; same-key byte mismatches fail as immutable collisions.

## Production invariant

M11.6 leaves production byte-for-byte unchanged:

- release: `20260708T040116Z-69a9f445699a`
- manifest SHA-256: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- pointer SHA-256: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

Issue #30 remains open and receives no entry.
